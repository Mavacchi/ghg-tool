"""Reconciliation router -- snapshot lifecycle and diff endpoints.

Three endpoints (FR-26 / ESRS 2 BP-2 / CSRD Article 23 restatement):

  POST /api/v1/reconciliation/snapshots
      Freeze the current consolidated emissions into a calc.report_snapshots
      row.  esg_manager only.  Writes a calc.audit_log row in the same
      transaction and forwards a SIEM event.

  GET  /api/v1/reconciliation/snapshots?anno=YYYY
      List snapshots for the active tenant + year.  All roles.

  GET  /api/v1/reconciliation/diff?anno=YYYY&snapshot_id=...
      Compute the reconciliation delta between a named snapshot and the
      CURRENT consolidated state.  Read-only; never mutates.  All roles.

Errors follow RFC 7807; correlation_id is preserved on every response.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission, require_role
from ghg_tool.application.services.reconciliation_service import (
    ReconciliationDelta,
    ReconciliationResult,
    reconcile,
)
from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.security import siem

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/reconciliation", tags=["reconciliation"])


# ---------------------------------------------------------------------------
# Request / response schemas (kept local: tightly coupled to this router)
# ---------------------------------------------------------------------------
class SnapshotCreateRequest(BaseModel):
    """Body for POST /snapshots."""

    anno: int = Field(..., ge=2020, le=2099)
    snapshot_kind: str = Field(..., pattern=r"^(CSRD_FINAL|EU_ETS_FINAL|INTERIM)$")
    notes: str | None = Field(default=None, max_length=2000)
    pdf_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class SnapshotCreateResponse(BaseModel):
    """Response for POST /snapshots."""

    id: uuid.UUID
    rows_frozen: int
    taken_at: datetime
    correlation_id: str | None = None


class SnapshotListItem(BaseModel):
    """One row of GET /snapshots."""

    id: uuid.UUID
    snapshot_kind: str
    anno: int
    taken_at: datetime
    taken_by: str
    pdf_sha256: str | None
    notes: str | None
    rows_frozen: int


class ReconciliationDeltaSchema(BaseModel):
    """Per-row delta API view."""

    scope: int
    sub_scope: str
    codice_sito: str | None
    anno: int
    prior_tco2e: Decimal | None
    current_tco2e: Decimal | None
    abs_delta: Decimal
    pct_delta: Decimal | None
    cause_category: str
    material: bool


class ReconciliationDiffResponse(BaseModel):
    """Response for GET /diff."""

    snapshot_id: uuid.UUID
    anno: int
    total_prior: Decimal
    total_current: Decimal
    total_abs_delta: Decimal
    total_delta_pct: Decimal | None
    material_count: int
    restatement_required: bool
    cause_breakdown: dict[str, Decimal]
    rows: list[ReconciliationDeltaSchema]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_emission_dict(row: Any) -> dict[str, Any]:
    """Convert a result mapping into the dict shape reconcile() expects."""
    m = row._mapping  # noqa: SLF001
    return {
        "scope": int(m["scope"]),
        "sub_scope": str(m["sub_scope"]),
        "codice_sito": m["codice_sito"],
        "anno": int(m["anno"]),
        "tco2e": str(m["tco2e"]),
        "factor_id": str(m["factor_id"]) if m["factor_id"] else None,
        "factor_version": m["factor_version"],
        "gwp_set": m["gwp_set"],
    }


def _delta_to_schema(d: ReconciliationDelta) -> ReconciliationDeltaSchema:
    return ReconciliationDeltaSchema(
        scope=d.scope,
        sub_scope=d.sub_scope,
        codice_sito=d.codice_sito,
        anno=d.anno,
        prior_tco2e=d.prior_tco2e,
        current_tco2e=d.current_tco2e,
        abs_delta=d.abs_delta,
        pct_delta=d.pct_delta,
        cause_category=d.cause_category,
        material=d.material,
    )


def _result_totals_by_scope(rows: list[dict[str, Any]]) -> dict[str, Decimal]:
    """Aggregate frozen rows into {'scope1','scope2_lb','scope2_mb','scope3'}."""
    totals: dict[str, Decimal] = {
        "scope1": Decimal("0"),
        "scope2_lb": Decimal("0"),
        "scope2_mb": Decimal("0"),
        "scope3": Decimal("0"),
        "biogenic_memo": Decimal("0"),
    }
    for r in rows:
        scope = int(r["scope"])
        sub = str(r["sub_scope"])
        tco2e = Decimal(str(r["tco2e"]))
        if scope == 1:
            totals["scope1"] += tco2e
        elif scope == 2 and sub.endswith("_LB"):
            totals["scope2_lb"] += tco2e
        elif scope == 2 and sub.endswith("_MB"):
            totals["scope2_mb"] += tco2e
        elif scope == 3:
            totals["scope3"] += tco2e
    return totals


async def _fetch_active_emissions(
    session: AsyncSession, tenant_id: uuid.UUID, anno: int
) -> list[dict[str, Any]]:
    """Read active emission rows for tenant+anno (RLS is already scoping)."""
    result = await session.execute(
        text(
            """
            SELECT scope, sub_scope, codice_sito, anno, tco2e,
                   factor_id, factor_version, gwp_set
            FROM calc.emissions_consolidated
            WHERE tenant_id = :tid
              AND anno = :anno
              AND valid_to IS NULL
            """
        ),
        {"tid": str(tenant_id), "anno": anno},
    )
    return [_row_to_emission_dict(r) for r in result]


# ---------------------------------------------------------------------------
# POST /snapshots
# ---------------------------------------------------------------------------
@router.post(
    "/snapshots",
    response_model=SnapshotCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Freeze a calc.report_snapshots row (esg_manager only)",
    description=(
        "Captures the current consolidated emissions for the requested year "
        "as an immutable snapshot.  Used as the reference state for CSRD "
        "Article 23 restatement diffs.  Writes a calc.audit_log row and "
        "emits a SIEM event in the same transaction."
    ),
    responses={
        201: {"description": "Snapshot created"},
        401: {"description": "Not authenticated"},
        403: {"description": "esg_manager role required"},
        422: {"description": "Validation error"},
    },
)
async def create_snapshot(
    body: SnapshotCreateRequest,
    user: CurrentUser = Depends(require_role("esg_manager")),
    session: AsyncSession = Depends(get_db),
) -> SnapshotCreateResponse:
    """Freeze the current consolidated emissions into a new snapshot row."""
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        tenant_id=user.tenant_id,
        anno=body.anno,
        snapshot_kind=body.snapshot_kind,
    )
    log.info("create_snapshot_requested")

    tenant_uuid = uuid.UUID(user.tenant_id)
    now_utc = datetime.now(tz=UTC)
    snapshot_id = uuid.uuid4()
    snapshot_correlation_id = (
        uuid.UUID(correlation_id) if correlation_id else uuid.uuid4()
    )

    try:
        frozen_rows = await _fetch_active_emissions(session, tenant_uuid, body.anno)
        totals = _result_totals_by_scope(frozen_rows)

        await session.execute(
            text(
                """
                INSERT INTO calc.report_snapshots (
                    id, tenant_id, snapshot_kind, anno,
                    snapshot_correlation_id, taken_at, taken_by,
                    pdf_sha256, frozen_emissions, frozen_totals, notes
                ) VALUES (
                    :id, :tid, :kind, :anno,
                    :scid, :taken_at, :taken_by,
                    :sha, CAST(:rows AS jsonb), CAST(:totals AS jsonb), :notes
                )
                """
            ),
            {
                "id": str(snapshot_id),
                "tid": str(tenant_uuid),
                "kind": body.snapshot_kind,
                "anno": body.anno,
                "scid": str(snapshot_correlation_id),
                "taken_at": now_utc,
                "taken_by": user.sub,
                "sha": body.pdf_sha256,
                # Use the json module via json.dumps with str-cast Decimals
                # for deterministic serialisation.
                "rows": _json_dumps_decimal(frozen_rows),
                "totals": _json_dumps_decimal(
                    {k: str(v) for k, v in totals.items()}
                ),
                "notes": body.notes,
            },
        )

        # Audit row in the SAME transaction (ISAE 3000 §40).
        session.add(
            AuditLog(
                tenant_id=tenant_uuid,
                correlation_id=snapshot_correlation_id,
                user_role=user.role,
                action="report_snapshot_created",
                resource="report_snapshots",
                resource_id=snapshot_id,
                request_method="POST",
                request_path="/api/v1/reconciliation/snapshots",
                status_code=201,
                after_state={
                    "snapshot_kind": body.snapshot_kind,
                    "anno": body.anno,
                    "rows_frozen": len(frozen_rows),
                    "pdf_sha256": body.pdf_sha256,
                    "notes": body.notes,
                },
            )
        )
        await session.flush()
    except SQLAlchemyError as exc:
        log.error(
            "create_snapshot_db_failure",
            exc_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Snapshot creation failed",
                "correlation_id": correlation_id,
            },
        ) from exc

    # Best-effort SIEM forward (never blocks the response).
    siem.emit(
        event="report_snapshot_created",
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user_sub=user.sub,
        severity="INFO",
        payload={
            "snapshot_id": str(snapshot_id),
            "snapshot_kind": body.snapshot_kind,
            "anno": body.anno,
            "rows_frozen": len(frozen_rows),
        },
    )

    log.info("snapshot_created", snapshot_id=str(snapshot_id), rows=len(frozen_rows))
    return SnapshotCreateResponse(
        id=snapshot_id,
        rows_frozen=len(frozen_rows),
        taken_at=now_utc,
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# GET /snapshots
# ---------------------------------------------------------------------------
@router.get(
    "/snapshots",
    response_model=list[SnapshotListItem],
    status_code=status.HTTP_200_OK,
    summary="List snapshots for the active tenant + year",
    responses={
        200: {"description": "List of snapshots"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
    },
)
async def list_snapshots(
    anno: int = Query(..., ge=2020, le=2099),
    user: CurrentUser = Depends(require_permission("reconciliation", "read")),
    session: AsyncSession = Depends(get_db),
) -> list[SnapshotListItem]:
    """Return all snapshots for the requested year, newest first."""
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8], anno=anno)
    log.info("list_snapshots")

    try:
        result = await session.execute(
            text(
                """
                SELECT id, snapshot_kind, anno, taken_at, taken_by,
                       pdf_sha256, notes,
                       jsonb_array_length(frozen_emissions) AS rows_frozen
                FROM calc.report_snapshots
                WHERE tenant_id = :tid AND anno = :anno
                ORDER BY taken_at DESC
                """
            ),
            {"tid": user.tenant_id, "anno": anno},
        )
        rows = list(result)
    except SQLAlchemyError as exc:
        log.error("list_snapshots_db_failure", exc_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Snapshot list failed",
                "correlation_id": correlation_id,
            },
        ) from exc

    return [
        SnapshotListItem(
            id=r._mapping["id"],  # noqa: SLF001
            snapshot_kind=r._mapping["snapshot_kind"],  # noqa: SLF001
            anno=r._mapping["anno"],  # noqa: SLF001
            taken_at=r._mapping["taken_at"],  # noqa: SLF001
            taken_by=r._mapping["taken_by"],  # noqa: SLF001
            pdf_sha256=r._mapping["pdf_sha256"],  # noqa: SLF001
            notes=r._mapping["notes"],  # noqa: SLF001
            rows_frozen=int(r._mapping["rows_frozen"] or 0),  # noqa: SLF001
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# GET /diff
# ---------------------------------------------------------------------------
@router.get(
    "/diff",
    response_model=ReconciliationDiffResponse,
    status_code=status.HTTP_200_OK,
    summary="Reconcile a snapshot against the current consolidated state",
    description=(
        "Read-only: never mutates data.  Returns the full ReconciliationResult "
        "with per-row deltas, cause breakdown, and the CSRD Article 23 "
        "restatement flag."
    ),
    responses={
        200: {"description": "Reconciliation result"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        404: {"description": "Snapshot not found"},
    },
)
async def get_reconciliation_diff(
    anno: int = Query(..., ge=2020, le=2099),
    snapshot_id: uuid.UUID = Query(...),
    user: CurrentUser = Depends(require_permission("reconciliation", "read")),
    session: AsyncSession = Depends(get_db),
) -> ReconciliationDiffResponse:
    """Run reconcile() between the named snapshot and the current state."""
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        anno=anno,
        snapshot_id=str(snapshot_id),
    )
    log.info("reconcile_diff_requested")

    try:
        snap_result = await session.execute(
            text(
                """
                SELECT frozen_emissions
                FROM calc.report_snapshots
                WHERE id = :sid AND tenant_id = :tid AND anno = :anno
                """
            ),
            {"sid": str(snapshot_id), "tid": user.tenant_id, "anno": anno},
        )
        snap_row = snap_result.first()
    except SQLAlchemyError as exc:
        log.error("reconcile_db_failure", exc_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Reconciliation read failed",
                "correlation_id": correlation_id,
            },
        ) from exc

    if snap_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"Snapshot {snapshot_id} not found for anno={anno}",
                "correlation_id": correlation_id,
            },
        )

    snapshot_emissions: list[dict[str, Any]] = list(snap_row._mapping["frozen_emissions"])  # noqa: SLF001
    current_emissions = await _fetch_active_emissions(
        session, uuid.UUID(user.tenant_id), anno
    )

    result: ReconciliationResult = reconcile(
        snapshot_emissions=snapshot_emissions,
        current_emissions=current_emissions,
    )

    return ReconciliationDiffResponse(
        snapshot_id=snapshot_id,
        anno=anno,
        total_prior=result.total_prior,
        total_current=result.total_current,
        total_abs_delta=result.total_abs_delta,
        total_delta_pct=result.total_delta_pct,
        material_count=result.material_count,
        restatement_required=result.restatement_required,
        cause_breakdown=dict(result.cause_breakdown),
        rows=[_delta_to_schema(d) for d in result.rows],
    )


# ---------------------------------------------------------------------------
# JSON serialisation helper (Decimal-safe)
# ---------------------------------------------------------------------------
def _json_dumps_decimal(obj: Any) -> str:
    """Serialise ``obj`` to JSON with Decimal -> str coercion.

    JSONB columns accept any string; this keeps numeric precision intact and
    avoids float-binary contamination.
    """
    import json  # noqa: PLC0415

    def _default(v: Any) -> Any:
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, uuid.UUID):
            return str(v)
        raise TypeError(f"Unserialisable type: {type(v).__name__}")

    return json.dumps(obj, default=_default, sort_keys=True)


# ---------------------------------------------------------------------------
# C-008: explicit 405 DELETE handler -- reconciliation snapshots are append-only.
# ---------------------------------------------------------------------------


@router.delete(
    "/snapshots/{snapshot_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    summary="DELETE not allowed -- reconciliation snapshots are append-only",
    description=(
        "Reconciliation snapshots are immutable once created. "
        "Corrections must be submitted as new snapshots."
    ),
    responses={405: {"description": "Method not allowed"}},
)
async def delete_snapshot_not_allowed(snapshot_id: uuid.UUID) -> dict[str, str]:
    """Return 405 for DELETE on reconciliation snapshots.

    C-008: The append-only invariant is enforced at the API layer.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Reconciliation snapshots are append-only; use deactivation",
    )
