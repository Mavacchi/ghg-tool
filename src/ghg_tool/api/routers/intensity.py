"""Intensity router — GET /api/v1/intensity — ESRS E1-6 §45 intensity ratios (FR-25, FR-26).

Reads from the ``calc.v_intensity_metrics`` security-barrier view (M7),
which wraps ``calc.mv_intensity_metrics`` with a per-request tenant
filter sourced from ``current_setting('app.tenant_id', true)::uuid``.
SEC-P0-002: direct MV access is REVOKEd from the application role.
When the view is absent (wave-3 pipeline not yet run), a stub empty
response is returned so the endpoint is testable without a live database.

RBAC: all three roles may read (editor, admin, viewer).
Read-only: no POST / PUT / PATCH / DELETE on ``/api/v1/intensity*``.

Denominator types (FR-26):
  EUR_revenue  — tCO2e per EUR revenue
  m2_production — tCO2e per m² production area
  FTE          — tCO2e per full-time-equivalent headcount
  kg_product   — tCO2e per kg product (tonne basis in source data)

SEC-P0-003 — Cross-tenant isolation:
  The ``tenant_id`` query parameter has been removed.  The tenant is now
  sourced exclusively from the validated JWT claim (``user.tenant_id``).
  This closes the trivial cross-tenant data read that was possible when a
  caller supplied an arbitrary ``tenant_id`` in the query string.  The SQL
  binding is *always* the JWT-derived value — client-supplied values are
  neither read nor forwarded.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.intensity_schemas import IntensityResponse, IntensityRow
from ghg_tool.domain.exceptions.calc_errors import (
    InvalidGWPSetError,
    InvalidIntensityDenominatorError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/intensity", tags=["intensity"])

# ---------------------------------------------------------------------------
# Type aliases for annotated query params
# ---------------------------------------------------------------------------

_DenominatorType = Literal["EUR_revenue", "m2_production", "FTE", "kg_product"]

_CURRENT_YEAR: int = dt.datetime.now(dt.UTC).year
_DEFAULT_GWP: str = "AR6"


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="ESRS E1-6 §45 intensity ratios (FR-25)",
    description=(
        "Returns intensity metrics (tCO2e per denominator unit) for the caller's "
        "tenant, denominator type, and year range.  The tenant is sourced exclusively "
        "from the validated JWT claim (SEC-P0-003 — cross-tenant isolation).  "
        "Reads from ``calc.v_intensity_metrics`` materialised view.  All authenticated "
        "roles may read.  A stub empty response is returned when the view is not yet "
        "available (wave-3 pipeline pending)."
        "\n\n"
        "Denominator types (FR-26):\n"
        "  - ``EUR_revenue``:    tCO2e per EUR revenue\n"
        "  - ``m2_production``:  tCO2e per m² production area\n"
        "  - ``FTE``:            tCO2e per full-time-equivalent headcount (REV-017)\n"
        "  - ``kg_product``:     tCO2e per kg product (tonne basis in source data)\n"
        "\n\n"
        "The ``hr_confirmation_date`` field on each row is populated only when "
        "``denominator_type=FTE``; it traces the HR-confirmed effective date per REV-017."
    ),
    response_model=IntensityResponse,
    responses={
        200: {"description": "Intensity metrics response"},
        400: {"description": "Invalid gwp_set or denominator_type"},
        401: {"description": "Not authenticated"},
        403: {"description": "Role not permitted"},
    },
)
async def get_intensity(
    denominator_type: Annotated[
        _DenominatorType,
        Query(
            description=(
                "Denominator type (FR-26): "
                "EUR_revenue | m2_production | FTE | kg_product"
            )
        ),
    ],
    anno_from: Annotated[
        int,
        Query(description="First reporting year (inclusive)", ge=2000, le=2100),
    ] = _CURRENT_YEAR - 4,
    anno_to: Annotated[
        int,
        Query(description="Last reporting year (inclusive)", ge=2000, le=2100),
    ] = _CURRENT_YEAR,
    codice_sito: Annotated[
        str | None,
        Query(description="Site code filter; omit for multi-site aggregate"),
    ] = None,
    gwp_set: Annotated[
        Literal["AR6", "AR5"] | None,
        Query(description="GWP characterisation set; defaults to AR6"),
    ] = None,
    user: CurrentUser = Depends(require_permission("intensity", "read")),
    session: AsyncSession = Depends(get_db),
) -> IntensityResponse:
    """Return intensity metrics for the caller's tenant and requested filters.

    Reads from ``calc.v_intensity_metrics``.  Filters are pushed down to
    the DB query (REV-021/022 query-pushdown principle) — no in-Python
    post-filtering.

    SEC-P0-003: ``tenant_id`` is sourced from the validated JWT claim
    (``user.tenant_id``), never from the query string.  This prevents
    cross-tenant data reads.

    Args:
        denominator_type: One of the four FR-26 denominator types.
        anno_from: First reporting year to include (default: current year - 4).
        anno_to: Last reporting year to include (default: current year).
        codice_sito: Optional site code filter; if omitted, multi-site aggregate rows
            are returned (``codice_sito IS NULL`` in the MV).
        gwp_set: GWP set filter; defaults to ``AR6`` when omitted.
        user: Authenticated user with intensity:read permission.
        session: Async DB session with RLS GUCs set by the auth middleware.

    Returns:
        An ``IntensityResponse`` with matching intensity rows.
        Returns a stub (empty rows) when the MV is not yet available.

    Raises:
        HTTPException 400: When the service raises ``InvalidGWPSetError`` or
            ``InvalidIntensityDenominatorError`` for the supplied parameters.
        HTTPException 401: When no valid JWT is present.
        HTTPException 403: When the caller's role lacks intensity:read permission.
    """
    from fastapi import HTTPException

    # SEC-P0-003: tenant_id is always sourced from the JWT — never from the
    # query string.  Client-supplied tenant_id values are silently ignored.
    tenant_id = user.tenant_id

    resolved_gwp = gwp_set if gwp_set is not None else _DEFAULT_GWP
    correlation_id = get_correlation_id() or ""

    log = logger.bind(
        correlation_id=correlation_id,
        denominator_type=denominator_type,
        gwp_set=resolved_gwp,
        # Truncate tenant_id to first 8 chars — no PII (it is a UUID)
        tenant_id=tenant_id[:8],
    )
    log.info("get_intensity", anno_from=anno_from, anno_to=anno_to, codice_sito=codice_sito)

    # Validate gwp_set at the router boundary so we can return RFC 7807 400
    if resolved_gwp not in {"AR6", "AR5"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "about:blank",
                "title": "Bad Request",
                "status": 400,
                "detail": (
                    f"Invalid gwp_set={resolved_gwp!r}. "
                    "Allowed values: 'AR6', 'AR5'."
                ),
                "correlation_id": correlation_id,
            },
        )

    try:
        # All filters pushed to SQL; no in-Python post-filtering
        query = text(
            "SELECT "
            "  anno, codice_sito, scope_label, "
            "  intensity_value, denominator_value, denominator_unit, "
            "  gwp_set, factor_source, factor_version, methodology, "
            "  hr_confirmation_date, "
            "  confidence_interval_lower, confidence_interval_upper, "
            "  correlation_id "
            "FROM calc.v_intensity_metrics "
            "WHERE tenant_id = :tenant_id "
            "  AND denominator_type = :denom "
            "  AND gwp_set = :gwp "
            "  AND anno >= :anno_from "
            "  AND anno <= :anno_to "
            "  AND (:codice_sito IS NULL OR codice_sito = :codice_sito)"
        )
        result = await session.execute(
            query,
            {
                "tenant_id": tenant_id,
                "denom": denominator_type,
                "gwp": resolved_gwp,
                "anno_from": anno_from,
                "anno_to": anno_to,
                "codice_sito": codice_sito,
            },
        )
        raw_rows = [dict(r._mapping) for r in result]

        rows = [IntensityRow(**r) for r in raw_rows]

        log.info("get_intensity_ok", result_rows_count=len(rows))

        return IntensityResponse(
            rows=rows,
            denominator_type=denominator_type,
            gwp_set=resolved_gwp,
            anno_from=anno_from,
            anno_to=anno_to,
            correlation_id=correlation_id,
            as_of=dt.datetime.now(tz=dt.UTC),
        )

    except (ProgrammingError, OperationalError) as exc:
        # MV not yet created (wave-3 pipeline pending) — return empty stub
        log.warning(
            "mv_intensity_metrics not available, returning stub",
            exc_type=type(exc).__name__,
        )
        return IntensityResponse(
            rows=[],
            denominator_type=denominator_type,
            gwp_set=resolved_gwp,
            anno_from=anno_from,
            anno_to=anno_to,
            correlation_id=correlation_id,
            as_of=dt.datetime.now(tz=dt.UTC),
            **{"_note": "calc.v_intensity_metrics not yet available — created in wave 3"},
        )

    except InvalidGWPSetError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "about:blank",
                "title": "Bad Request",
                "status": 400,
                "detail": str(exc),
                "correlation_id": correlation_id,
            },
        ) from exc

    except InvalidIntensityDenominatorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "about:blank",
                "title": "Bad Request",
                "status": 400,
                "detail": str(exc),
                "correlation_id": correlation_id,
            },
        ) from exc
