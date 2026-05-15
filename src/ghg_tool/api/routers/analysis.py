"""Scope 3 hot-spot analysis endpoint (Wave4 Task C).

Endpoint:
    GET /api/v1/analysis/hotspots?anno=2024&top_n=5

RBAC: ``emissions.read`` permission (viewer role and above).

Returns a ``HotspotReport`` JSON object with:
  - ``total_s3_tco2e``: total active Scope 3 tCO2e for the year.
  - ``hotspots``: up to ``top_n`` categories ranked by tCO2e descending.
  - ``methodology_note``: GHG Protocol Scope 3 Standard §10 citation.

HTTP status codes:
  200 — successful report (empty hotspots list when S3 total = 0).
  404 — no emission rows at all for the requested anno.
  403 — insufficient permissions.
  422 — validation error (anno out of range, etc.).

References:
  GHG Protocol Scope 3 Standard (2011) §10 (hot-spot analysis).
  CSRD ESRS E1-6 §44.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.application.services.hotspot_analysis_service import (
    HotspotItem,
    HotspotReport,
    NoDataForAnnoError,
    compute_hotspots,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


# ---------------------------------------------------------------------------
# Response schemas (Pydantic v2 — serialisable counterparts of dataclasses)
# ---------------------------------------------------------------------------

class HotspotItemSchema(BaseModel):
    """Serialisable Pydantic schema for a single hot-spot entry.

    Attributes:
        sub_scope: Sub-scope code (e.g. 'Cat1', 'Cat3_WTT_FUEL').
        tco2e: Absolute tCO2e for the category.
        pct_of_total: Percentage share of total S3 tCO2e (0–100).
        priority: Materiality tier (HIGH / MEDIUM / LOW).
    """

    model_config = ConfigDict(frozen=True)

    sub_scope: str = Field(description="Sub-scope code from emissions_consolidated")
    tco2e: Decimal = Field(description="Absolute tCO2e for this category")
    pct_of_total: Decimal = Field(
        description="Percentage share of total Scope 3 tCO2e (0–100)"
    )
    priority: str = Field(
        description=(
            "Materiality tier: HIGH (>20%), MEDIUM (5–20%), LOW (<5%) "
            "per GHG Protocol Scope 3 Standard §10"
        )
    )

    @classmethod
    def from_domain(cls, item: HotspotItem) -> "HotspotItemSchema":
        """Convert a domain dataclass to a serialisable schema.

        Args:
            item: Domain ``HotspotItem`` dataclass.

        Returns:
            ``HotspotItemSchema`` instance.
        """
        return cls(
            sub_scope=item.sub_scope,
            tco2e=item.tco2e,
            pct_of_total=item.pct_of_total,
            priority=item.priority,
        )


class HotspotReportSchema(BaseModel):
    """Serialisable Pydantic schema for the full hot-spot report.

    Attributes:
        tenant_id: UUID string of the tenant.
        anno: Reporting year analysed.
        total_s3_tco2e: Sum of all active Scope 3 tCO2e rows for the year.
        hotspots: Top-N categories ranked by tCO2e descending.
        methodology_note: Normative methodology citation.
    """

    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(description="Tenant UUID")
    anno: int = Field(description="Reporting year")
    total_s3_tco2e: Decimal = Field(
        description="Total active Scope 3 tCO2e for the year"
    )
    hotspots: list[HotspotItemSchema] = Field(
        description="Top-N categories by tCO2e, highest first"
    )
    methodology_note: str = Field(
        description="Normative methodology citation (GHG Protocol Scope 3 §10)"
    )

    @classmethod
    def from_domain(cls, report: HotspotReport) -> "HotspotReportSchema":
        """Convert a domain dataclass to a serialisable schema.

        Args:
            report: Domain ``HotspotReport`` dataclass.

        Returns:
            ``HotspotReportSchema`` instance.
        """
        return cls(
            tenant_id=report.tenant_id,
            anno=report.anno,
            total_s3_tco2e=report.total_s3_tco2e,
            hotspots=[HotspotItemSchema.from_domain(h) for h in report.hotspots],
            methodology_note=report.methodology_note,
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/hotspots",
    status_code=status.HTTP_200_OK,
    response_model=HotspotReportSchema,
    summary="Scope 3 hot-spot analysis",
    description=(
        "Identifies the top-N Scope 3 categories most material in proportion "
        "to total Scope 3 tCO2e for the given reporting year.\n\n"
        "Returns HTTP 200 with an empty ``hotspots`` list when the year has "
        "rows for other scopes but no active Scope 3 data.\n\n"
        "Returns HTTP 404 when no emission rows exist at all for the "
        "requested anno.\n\n"
        "Priority tiers follow GHG Protocol Scope 3 Standard §10: "
        "HIGH > 20%, MEDIUM 5–20%, LOW < 5% of total Scope 3 tCO2e.\n\n"
        "Requires ``emissions.read`` permission (viewer role or above)."
    ),
    responses={
        200: {"description": "Hot-spot report (hotspots list may be empty)"},
        403: {"description": "Insufficient permission (requires emissions.read)"},
        404: {"description": "No emission data found for the requested anno"},
        422: {"description": "Validation error (anno out of range, etc.)"},
    },
)
async def get_hotspots(
    user: Annotated[CurrentUser, Depends(require_permission("emissions", "read"))],
    session: Annotated[AsyncSession, Depends(get_db)],
    anno: int = Query(
        ge=2000,
        le=2100,
        description="Reporting year to analyse (e.g. 2024)",
    ),
    top_n: int = Query(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of categories to return (default 5, max 20)",
    ),
) -> HotspotReportSchema:
    """Return a Scope 3 hot-spot analysis report for the given year.

    Queries ``calc.emissions_consolidated`` directly via a CTE that aggregates
    tCO2e by ``sub_scope`` and computes each category's percentage of total
    Scope 3.  Results are sorted by tCO2e descending and capped at ``top_n``.

    Args:
        user: Authenticated user with emissions.read permission.
        session: Async DB session with RLS GUCs pre-set.
        anno: Reporting year to analyse.
        top_n: Maximum number of categories to include.

    Returns:
        ``HotspotReportSchema`` with ranked categories and methodology note.

    Raises:
        HTTPException 404: When no rows exist for the (tenant, anno) pair.
    """
    cid = get_correlation_id()
    log = logger.bind(
        correlation_id=cid,
        user=user.sub[:8],
        anno=anno,
        top_n=top_n,
    )
    log.info("hotspot_analysis_request")

    try:
        report = await compute_hotspots(
            session,
            tenant_id=user.tenant_id,
            anno=anno,
            top_n=top_n,
        )
    except NoDataForAnnoError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": (
                    f"No emission data found for anno={anno}. "
                    "Ensure the calc run has been completed for this year."
                ),
                "correlation_id": cid,
            },
        )

    log.info(
        "hotspot_analysis_complete",
        total_s3_tco2e=str(report.total_s3_tco2e),
        categories_returned=len(report.hotspots),
    )
    return HotspotReportSchema.from_domain(report)
