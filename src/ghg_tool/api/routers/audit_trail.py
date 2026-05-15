"""Audit trail router — GET /api/v1/audit-trail (FR-22, FR-29).

Accessible to esg_manager and auditor only.  Returns the full data lineage
from raw ingestion row → calculated emission → factor applied, filterable by
correlation_id, year, and site.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.kpi_schemas import (
    AuditTrailEntry,
    AuditTrailResponse,
    PaginationMeta,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/audit-trail", tags=["audit-trail"])


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="Audit trail: emission → factor provenance lineage",
    description=(
        "Returns a joined view of calc.emissions_consolidated ⟶ ref.factor_catalog "
        "with optional raw ingestion row metadata. "
        "Filterable by correlation_id, anno, codice_sito. "
        "esg_manager and auditor roles only (FR-22, FR-31)."
    ),
    response_model=AuditTrailResponse,
    responses={
        200: {"description": "Audit trail rows"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — esg_manager or auditor required"},
        500: {"description": "Internal error retrieving audit trail"},
    },
)
async def get_audit_trail(
    correlation_id_filter: UUID | None = None,
    anno: int | None = None,
    codice_sito: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    user: CurrentUser = Depends(require_permission("audit_trail", "read")),
    session: AsyncSession = Depends(get_db),
) -> AuditTrailResponse:
    """Return emission-to-factor lineage for audit purposes.

    Args:
        correlation_id_filter: Optional filter on the run correlation UUID.
        anno: Optional filter on reporting year.
        codice_sito: Optional filter on site code.
        limit: Maximum rows to return (1–1000).
        user: Authenticated user with audit_trail:read permission.
        session: Authenticated DB session.

    Returns:
        An ``AuditTrailResponse`` with ``entries`` list and pagination metadata.

    Raises:
        HTTPException: 500 on internal DB error (detail never exposes internals).
    """
    request_cid = get_correlation_id()
    log = logger.bind(correlation_id=request_cid, user=user.sub[:8])
    log.info("get_audit_trail", anno=anno, codice_sito=codice_sito)

    query_sql = """
        SELECT
            e.id               AS emission_id,
            e.correlation_id,
            e.scope,
            e.sub_scope,
            e.codice_sito,
            e.anno,
            e.tco2e,
            e.gwp_set,
            e.methodology,
            e.regulatory_stream,
            e.calc_timestamp,
            e.created_by,
            e.factor_source,
            e.factor_version,
            e.valid_from,
            e.valid_to,
            e.superseded_by,
            e.reason_code,
            e.raw_row_id,
            f.factor_id        AS factor_string_id,
            f.source           AS factor_provider,
            f.gwp_set          AS factor_gwp_set,
            f.value            AS factor_value,
            f.unit             AS factor_unit
        FROM calc.emissions_consolidated e
        LEFT JOIN ref.factor_catalog f ON f.id = e.factor_id
        WHERE 1=1
          AND (CAST(:cid AS uuid) IS NULL OR e.correlation_id = CAST(:cid AS uuid))
          AND (CAST(:anno AS integer) IS NULL OR e.anno = CAST(:anno AS integer))
          AND (CAST(:site AS text) IS NULL OR e.codice_sito = CAST(:site AS text))
        ORDER BY e.calc_timestamp DESC
        LIMIT CAST(:lim AS integer)
    """
    try:
        result = await session.execute(
            text(query_sql),
            {
                "cid": str(correlation_id_filter) if correlation_id_filter else None,
                "anno": anno,
                "site": codice_sito,
                "lim": min(limit, 1000),
            },
        )
        rows = [dict(r._mapping) for r in result]
        for r in rows:
            # Coerce non-JSON-native column types into the str/float the
            # AuditTrailEntry schema declares. Without this, Pydantic v2
            # raises ValidationError on `datetime` for the timestamp fields
            # (which `str | None` does not auto-coerce) and that escapes
            # the SQLAlchemyError-only except clause below, leaving the
            # global error middleware to substitute a generic 500.
            for k, v in r.items():
                if isinstance(v, UUID):
                    r[k] = str(v)
                elif isinstance(v, datetime | date):
                    r[k] = v.isoformat()
                elif isinstance(v, Decimal):
                    r[k] = float(v)
        entries = [AuditTrailEntry(**r) for r in rows]
        return AuditTrailResponse(
            entries=entries,
            pagination=PaginationMeta(count=len(entries)),
            correlation_id=request_cid or "",
        )
    except SQLAlchemyError as exc:
        log.error(
            "audit_trail query failed",
            exc_type=type(exc).__name__,
            exc_message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error retrieving audit trail",
        ) from exc


# ---------------------------------------------------------------------------
# C-009: explicit 405 DELETE handler -- audit trail is append-only.
# ---------------------------------------------------------------------------


@router.delete(
    "/",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    summary="DELETE not allowed -- audit trail is append-only",
    description="The audit trail is an immutable record. No entries may be deleted.",
    responses={405: {"description": "Method not allowed"}},
)
async def delete_audit_trail_not_allowed() -> dict[str, str]:
    """Return 405 for DELETE on the audit trail.

    C-009: The append-only invariant is enforced at the API layer.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Audit trail is append-only; entries cannot be deleted",
    )
