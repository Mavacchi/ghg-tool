"""KPIs router — GET /api/v1/kpis — dashboard-feed JSON (FR-29).

Reads from the ``calc.v_kpi_summary`` security-barrier view (M7), which
wraps ``calc.mv_kpi_summary`` with a per-request tenant filter sourced
from ``current_setting('app.tenant_id', true)::uuid``. SEC-P0-002:
direct MV access is REVOKEd from the application role.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.kpi_schemas import KpiSummaryResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/kpis", tags=["kpis"])


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="Dashboard KPI feed (all scopes, both years)",
    description=(
        "Returns aggregated KPIs for the GHG dashboard. Reads from "
        "calc.v_kpi_summary materialised view. All authenticated roles may read. "
        "Filters: anno (optional), gwp_set (optional, default AR6)."
    ),
    response_model=KpiSummaryResponse,
    responses={
        200: {"description": "KPI summary"},
        401: {"description": "Not authenticated"},
        503: {"description": "KPI materialised view not yet available"},
    },
)
async def get_kpis(
    anno: int | None = None,
    gwp_set: str = "AR6",
    user: CurrentUser = Depends(require_permission("kpis", "read")),
    session: AsyncSession = Depends(get_db),
) -> KpiSummaryResponse:
    """Return aggregated KPI data from the materialised view.

    Args:
        anno: Optional reporting year filter (2020–2099).
        gwp_set: GWP set to use for the KPI query ('AR6' or 'AR5').
        user: Authenticated user with kpis:read permission.
        session: Authenticated DB session with RLS GUCs.

    Returns:
        A ``KpiSummaryResponse`` with aggregated KPI values per scope/year/site.
        Returns a stub payload when the MV is not yet available.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8], gwp_set=gwp_set)
    log.info("get_kpis", anno=anno)

    try:
        query = text(
            "SELECT * FROM calc.v_kpi_summary "
            "WHERE (:gwp IS NULL OR gwp_set = :gwp) "
            "AND (:anno IS NULL OR reporting_year = :anno)"
        )
        result = await session.execute(query, {"gwp": gwp_set, "anno": anno})
        rows = [dict(r._mapping) for r in result]
        return KpiSummaryResponse(
            kpis=rows,
            gwp_set=gwp_set,
            correlation_id=correlation_id or "",
            as_of=datetime.now(tz=UTC),
        )
    except (ProgrammingError, OperationalError) as exc:
        # MV not yet created (wave 3 will create it); return stub
        log.warning(
            "mv_kpi_summary not available, returning stub",
            exc_type=type(exc).__name__,
        )
        return KpiSummaryResponse(
            kpis=[],
            gwp_set=gwp_set,
            correlation_id=correlation_id or "",
            as_of=datetime.now(tz=UTC),
            note="calc.v_kpi_summary not yet available — created in wave 3",
        )
