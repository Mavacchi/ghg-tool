"""Scope 3 hot-spot analysis service.

Ranks Scope 3 sub_scopes (categories 1 to 15) by absolute tCO2e, builds
the Pareto cumulative percentage, annotates each entry with the
year-over-year delta vs the previous reporting year and flags two risk
conditions:

  * ``flag_high_concentration``: True when the top-5 categories account
    for more than 80% of total Scope 3.  This is the classic Pareto
    "vital few" check and signals a concentration of mitigation
    leverage on a small set of suppliers / activities.
  * ``flag_yoy_outlier``: True when the absolute YoY delta exceeds
    2 sigma of historical YoY variation.  With only one prior year the
    historical sigma is undefined, so we fall back to a fixed +/- 20%
    threshold (documented).

Pure-function service: no DB access, no FastAPI, no Streamlit imports.
All emission quantities are handled as ``Decimal`` end-to-end per the
project-wide arithmetic policy.

References:
  * GHG Protocol Scope 3 Standard (2011), chapter 6 (prioritisation).
  * CSRD ESRS E1-6 §44 (gross Scope 3 by category).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.value_objects.scope3_categories import label_for

# --- Tunable thresholds -----------------------------------------------------

#: Top-N share of Scope 3 above which we raise a concentration warning.
CONCENTRATION_THRESHOLD: Decimal = Decimal("80")

#: Number of leading categories considered in the concentration check.
CONCENTRATION_TOP_N: int = 5

#: Multiplier on historical YoY sigma above which a delta is flagged.
YOY_SIGMA_MULTIPLIER: Decimal = Decimal("2")

#: Fallback +/- pct used when only a single prior year is available and the
#: historical sigma cannot be estimated.  Documented in the public docstring
#: of ``compute_hotspots``.
YOY_FALLBACK_PCT: Decimal = Decimal("20")


@dataclass(frozen=True)
class HotspotEntry:
    """One ranked Scope 3 category in the Pareto hot-spot table.

    Attributes:
        rank: 1-based position after descending sort by ``tco2e``.
        sub_scope: Raw sub_scope code from ``EmissionRecord`` (e.g. ``"Cat1"``).
        category_label: Human-readable Italian label (mirrors PDF builder).
        tco2e: Total emissions for this category in the current year.
        pct_of_scope3: Share of total Scope 3, expressed in 0..100.
        cumulative_pct: Running sum of ``pct_of_scope3`` down the ranking.
        yoy_delta_pct: Percentage change vs the prior year, or ``None`` when
            no prior data exists for this sub_scope.
        flag_high_concentration: True when the top-5 of the ranking carries
            more than 80% of total Scope 3 (same value on every entry).
        flag_yoy_outlier: True when ``|yoy_delta_pct|`` exceeds the 2 sigma
            historical threshold (or the +/- 20% fallback).
    """

    rank: int
    sub_scope: str
    category_label: str
    tco2e: Decimal
    pct_of_scope3: Decimal
    cumulative_pct: Decimal
    yoy_delta_pct: Decimal | None
    flag_high_concentration: bool
    flag_yoy_outlier: bool


def compute_hotspots(
    *,
    emissions_current: Iterable[EmissionRecord],
    emissions_prior: Iterable[EmissionRecord] | None = None,
    top_n: int = 10,
) -> list[HotspotEntry]:
    """Rank Scope 3 sub_scopes by tCO2e and build the Pareto hot-spot list.

    The function is pure: no I/O, no mutation of the input iterables.

    Behaviour:
      1. Filters both input iterables to ``scope == 3``.
      2. Groups by ``sub_scope`` and sums ``tco2e`` per group.
      3. Sorts descending by tCO2e (stable; ties broken by sub_scope code
         alphabetical order to keep results deterministic).
      4. Computes ``pct_of_scope3`` and ``cumulative_pct``.
      5. Annotates each entry with ``yoy_delta_pct`` when the prior year
         contains the matching sub_scope; ``None`` otherwise.
      6. Flags entries whose ``|yoy_delta_pct|`` exceeds 2 sigma of the
         historical YoY variation.  With only one pair of years available
         the sigma is undefined, so the threshold defaults to +/- 20%.
      7. Flags concentration when the top-5 of the ranking carries more
         than 80% of total Scope 3 (same value on every entry).

    Args:
        emissions_current: Iterable of ``EmissionRecord`` for the reporting
            year.  Rows with ``scope != 3`` are ignored.
        emissions_prior: Iterable of ``EmissionRecord`` for the previous
            year, used to compute YoY deltas.  ``None`` or empty disables
            the YoY annotation (all ``yoy_delta_pct`` will be ``None``).
        top_n: Maximum number of entries to return.  Defaults to 10.

    Returns:
        At most ``top_n`` ``HotspotEntry`` objects, ranked by tCO2e
        descending.  Empty list when no Scope 3 rows are present.
    """
    current_totals = _aggregate_scope3(emissions_current)
    if not current_totals:
        return []

    prior_totals = (
        _aggregate_scope3(emissions_prior) if emissions_prior is not None else {}
    )

    # Stable deterministic sort: primary key tco2e desc, secondary sub_scope asc.
    ranked: list[tuple[str, Decimal]] = sorted(
        current_totals.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )

    scope3_total = sum((v for _k, v in ranked), Decimal("0"))
    if scope3_total <= Decimal("0"):
        return []

    # Concentration flag: top-5 share > 80%.
    top_n_for_concentration = ranked[:CONCENTRATION_TOP_N]
    top_5_sum = sum((v for _k, v in top_n_for_concentration), Decimal("0"))
    concentration_pct = (top_5_sum / scope3_total) * Decimal("100")
    flag_high_concentration = concentration_pct > CONCENTRATION_THRESHOLD

    # Compute YoY deltas (None when prior is missing for that sub_scope).
    yoy_deltas: dict[str, Decimal | None] = {}
    for sub_scope, current_value in ranked:
        prior_value = prior_totals.get(sub_scope)
        if prior_value is None or prior_value <= Decimal("0"):
            yoy_deltas[sub_scope] = None
        else:
            yoy_deltas[sub_scope] = (
                (current_value - prior_value) / prior_value * Decimal("100")
            )

    # Outlier threshold.  Only one prior year is available in this signature
    # (current vs prior), so historical sigma is undefined: fall back to
    # +/- 20% per the public contract.
    outlier_threshold = YOY_FALLBACK_PCT

    # Build entries, accumulating cumulative_pct on the original ranking.
    entries: list[HotspotEntry] = []
    cumulative = Decimal("0")
    for rank, (sub_scope, value) in enumerate(ranked, start=1):
        pct = (value / scope3_total) * Decimal("100")
        cumulative += pct
        yoy = yoy_deltas[sub_scope]
        flag_outlier = (
            yoy is not None and abs(yoy) > outlier_threshold
        )
        entries.append(
            HotspotEntry(
                rank=rank,
                sub_scope=sub_scope,
                category_label=label_for(sub_scope),
                tco2e=value,
                pct_of_scope3=pct,
                cumulative_pct=cumulative,
                yoy_delta_pct=yoy,
                flag_high_concentration=flag_high_concentration,
                flag_yoy_outlier=flag_outlier,
            )
        )

    return entries[:top_n]


def _aggregate_scope3(
    emissions: Iterable[EmissionRecord] | None,
) -> dict[str, Decimal]:
    """Sum tCO2e grouped by sub_scope, restricted to scope == 3.

    Args:
        emissions: Iterable of ``EmissionRecord``; may be ``None``.

    Returns:
        Mapping ``sub_scope -> total tCO2e`` (Decimal).  Empty dict when
        the input is None / empty or contains no Scope 3 rows.
    """
    totals: dict[str, Decimal] = {}
    if emissions is None:
        return totals
    for record in emissions:
        if record.scope != 3:
            continue
        totals[record.sub_scope] = totals.get(record.sub_scope, Decimal("0")) + record.tco2e
    return totals


__all__ = ["HotspotEntry", "compute_hotspots"]
