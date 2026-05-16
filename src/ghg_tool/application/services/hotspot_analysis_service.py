"""SQL-backed Scope 3 hot-spot analysis service (Wave4 Task C).

Identifies the top-N Scope 3 categories (by sub_scope) that are most
material in proportion to the total Scope 3 tCO2e for a given tenant and
reporting year.

References:
  GHG Protocol Scope 3 Standard (2011) §10 (hot-spot analysis).
  CSRD ESRS E1-6 §44 (gross Scope 3 by category — disclosure requirement).
  IAASB ISA 320 §A3–§A14 (materiality thresholds).

Design decisions:
  • Pure SQL aggregation via a CTE — no Python-side loops over raw rows.
  • Decimal everywhere; no float arithmetic.
  • Returns HotspotReport(total=0, hotspots=[]) when no S3 data exists for
    the year (200 OK with empty list per spec), or raises 404 when anno has
    zero rows at all in the emissions table for the tenant.
  • ``priority`` thresholds: >20% = HIGH, 5–20% = MEDIUM, <5% = LOW
    (aligns with GHG Protocol Scope 3 Standard §10 materiality guidance).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Priority thresholds (GHG Protocol Scope 3 Standard §10)
# ---------------------------------------------------------------------------

_HIGH_PCT_THRESHOLD: Decimal = Decimal("20")
_MEDIUM_PCT_THRESHOLD: Decimal = Decimal("5")


def _priority(pct: Decimal) -> Literal["HIGH", "MEDIUM", "LOW"]:
    """Classify a category's percentage share as HIGH, MEDIUM, or LOW.

    Args:
        pct: Category share of total S3 tCO2e (0–100).

    Returns:
        ``"HIGH"`` if pct > 20%, ``"MEDIUM"`` if 5% ≤ pct ≤ 20%,
        ``"LOW"`` otherwise.
    """
    if pct > _HIGH_PCT_THRESHOLD:
        return "HIGH"
    if pct >= _MEDIUM_PCT_THRESHOLD:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Output value objects (frozen dataclasses for immutability)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HotspotItem:
    """One ranked Scope 3 category in the hot-spot report.

    Attributes:
        sub_scope: Sub-scope code from calc.emissions_consolidated
            (e.g. ``'Cat1'``, ``'Cat3_WTT_FUEL'``).
        tco2e: Absolute tCO2e for this category (Decimal).
        pct_of_total: Percentage share of total S3 tCO2e (Decimal, 0–100).
        priority: Materiality tier.  ``HIGH`` > 20%, ``MEDIUM`` 5–20%,
            ``LOW`` < 5%.  Aligns with GHG Protocol Scope 3 Standard §10.
    """

    sub_scope: str
    tco2e: Decimal
    pct_of_total: Decimal
    priority: Literal["HIGH", "MEDIUM", "LOW"]


@dataclass(frozen=True)
class HotspotReport:
    """Complete Scope 3 hot-spot analysis output for one tenant / year.

    Attributes:
        tenant_id: UUID string of the tenant.
        anno: Reporting year analysed.
        total_s3_tco2e: Sum of all active Scope 3 tCO2e rows for the year.
        hotspots: Top-N categories by tCO2e, highest first.
        methodology_note: Normative methodology citation.
    """

    tenant_id: str
    anno: int
    total_s3_tco2e: Decimal
    hotspots: list[HotspotItem]
    methodology_note: str


# ---------------------------------------------------------------------------
# Canonical methodology note
# ---------------------------------------------------------------------------

_METHODOLOGY_NOTE = (
    "Scope 3 hot-spot analysis following GHG Protocol Scope 3 Standard §10 "
    "(2011): categories ranked by absolute tCO2e contribution; material "
    "categories defined as those contributing the greatest proportion of "
    "estimated Scope 3 emissions.  Priority tiers: HIGH > 20%, MEDIUM 5–20%, "
    "LOW < 5% of total Scope 3 tCO2e."
)

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_HOTSPOT_SQL = """\
WITH s3_total AS (
    SELECT COALESCE(SUM(tco2e), 0) AS total
    FROM calc.emissions_consolidated
    WHERE tenant_id = CAST(:tid AS uuid)
      AND scope = 3
      AND anno = :anno
      AND valid_to IS NULL
),
per_cat AS (
    SELECT
        sub_scope,
        SUM(tco2e) AS tco2e
    FROM calc.emissions_consolidated
    WHERE tenant_id = CAST(:tid AS uuid)
      AND scope = 3
      AND anno = :anno
      AND valid_to IS NULL
    GROUP BY sub_scope
)
SELECT
    sub_scope,
    tco2e,
    ROUND(
        100.0 * tco2e / NULLIF((SELECT total FROM s3_total), 0),
        2
    ) AS pct
FROM per_cat
WHERE tco2e > 0
ORDER BY tco2e DESC
LIMIT :top_n
"""

_ANY_ANNO_SQL = """\
SELECT COUNT(*) AS row_count
FROM calc.emissions_consolidated
WHERE tenant_id = CAST(:tid AS uuid)
  AND anno = :anno
  AND valid_to IS NULL
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compute_hotspots(
    session: AsyncSession,
    tenant_id: str,
    anno: int,
    top_n: int = 5,
    threshold_pct: Decimal = Decimal("5.0"),
) -> HotspotReport:
    """Compute Scope 3 hot spots: categories contributing >threshold% of total.

    Returns the top ``top_n`` Scope 3 categories sorted by tCO2e descending,
    each annotated with its percentage of the total and a priority tier.

    Behaviour:
      • Returns an empty ``HotspotReport`` (total_s3_tco2e=0, hotspots=[])
        when the year has Scope 3 rows but all tco2e are zero, or when the
        top_n query returns no rows.
      • Raises ``NoDataForAnnoError`` when the tenant has zero emissions rows
        at all for the requested year (any scope) — callers translate this to
        HTTP 404.
      • Does NOT raise when Scope 3 total is 0 but other scopes have data
        for the same year (returns empty hotspots list with 200 OK).

    Args:
        session: Async SQLAlchemy session (RLS GUCs already set).
        tenant_id: UUID string of the tenant.
        anno: Reporting year to analyse.
        top_n: Maximum number of categories to return (default 5).
        threshold_pct: Minimum percentage threshold for inclusion (informational
            only — the SQL already returns the top ``top_n`` regardless; this
            parameter is retained for API compatibility and future filtering).

    Returns:
        ``HotspotReport`` with ranked hotspots.

    Raises:
        NoDataForAnnoError: When no rows exist for the (tenant, anno) pair.
    """
    from sqlalchemy import text  # noqa: PLC0415

    log = logger.bind(tenant_id=tenant_id[:8], anno=anno, top_n=top_n)
    log.info("hotspot_analysis_start")

    # Guard: 404 if the anno has no rows at all for this tenant.
    count_result = await session.execute(
        text(_ANY_ANNO_SQL),
        {"tid": tenant_id, "anno": anno},
    )
    row_count = count_result.scalar_one_or_none() or 0
    if int(row_count) == 0:
        raise NoDataForAnnoError(
            f"No emission rows found for tenant={tenant_id[:8]}... anno={anno}"
        )

    # Aggregate S3 total and per-category breakdown.
    result = await session.execute(
        text(_HOTSPOT_SQL),
        {"tid": tenant_id, "anno": anno, "top_n": top_n},
    )
    rows = result.mappings().all()

    if not rows:
        # Year has rows (other scopes) but no active Scope 3 data → empty report.
        log.info("hotspot_analysis_no_s3_data", anno=anno)
        return HotspotReport(
            tenant_id=tenant_id,
            anno=anno,
            total_s3_tco2e=Decimal("0"),
            hotspots=[],
            methodology_note=_METHODOLOGY_NOTE,
        )

    # Sum the tco2e from the per-category results to derive the total.
    # (The CTE already filters valid_to IS NULL, so this is correct.)
    total_tco2e: Decimal = sum(
        (Decimal(str(r["tco2e"])) for r in rows),
        Decimal("0"),
    )

    hotspots: list[HotspotItem] = []
    for row in rows:
        tco2e_val = Decimal(str(row["tco2e"]))
        pct_val = Decimal(str(row["pct"])) if row["pct"] is not None else Decimal("0")
        hotspots.append(
            HotspotItem(
                sub_scope=str(row["sub_scope"]),
                tco2e=tco2e_val,
                pct_of_total=pct_val,
                priority=_priority(pct_val),
            )
        )

    log.info(
        "hotspot_analysis_complete",
        total_s3_tco2e=str(total_tco2e),
        categories_found=len(hotspots),
    )

    return HotspotReport(
        tenant_id=tenant_id,
        anno=anno,
        total_s3_tco2e=total_tco2e,
        hotspots=hotspots,
        methodology_note=_METHODOLOGY_NOTE,
    )


class NoDataForAnnoError(ValueError):
    """Raised when no emission rows exist for the requested (tenant, anno).

    Callers (router layer) translate this to HTTP 404.
    """
