"""Reconciliation service -- compare a frozen snapshot to current emissions.

Pure-function module: no Streamlit, no FastAPI, no SQLAlchemy imports.  The
caller is responsible for loading the snapshot rows and the current
consolidated rows; this module performs the row-by-row diff, computes the
deltas, classifies the cause of each delta, and applies the CSRD Article 23
restatement materiality threshold.

Normative basis:
  - CSRD Directive (EU) 2022/2464 Article 23 -- restatement of comparative
    information when material errors or methodology changes are identified.
  - ESRS 2 BP-2 -- disclosures in relation to specific circumstances:
    restatement, comparability across reporting periods.
  - GHG Protocol Corporate Standard Chapter 5 -- "Tracking emissions over
    time" and the >5% significance threshold for base-year recalculation.

Materiality:
  A reconciliation triggers a restatement when EITHER
    * the aggregate absolute pct delta exceeds ``materiality_pct`` (default 5%)
    * OR any single (scope, sub_scope, codice_sito, anno) row exceeds
      ``2 * materiality_pct`` (default 10%) AND the absolute delta is at
      least ``materiality_tco2e`` (default 100 tCO2e) -- this filters
      noise from tiny denominators.

Decimal-end-to-end on tco2e: callers MUST pass Decimal or strings that
parse cleanly via ``Decimal(str(...))``.  No floats.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog

from ghg_tool.application.services.yoy_stats import (
    compute_yoy_baseline,
    threshold_pct,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Cause-category vocabulary (closed set -- mirror values must stay in sync
# with the API schema + Streamlit i18n keys).
# ---------------------------------------------------------------------------
CAUSE_FACTOR_UPDATE = "factor_update"
CAUSE_DATA_CORRECTION = "data_correction"
CAUSE_METHODOLOGY = "methodology"
CAUSE_UNKNOWN = "unknown"
CAUSE_NEW_ROW = "new_row"
CAUSE_WITHDRAWN_ROW = "withdrawn_row"

ALL_CAUSES: tuple[str, ...] = (
    CAUSE_FACTOR_UPDATE,
    CAUSE_DATA_CORRECTION,
    CAUSE_METHODOLOGY,
    CAUSE_UNKNOWN,
    CAUSE_NEW_ROW,
    CAUSE_WITHDRAWN_ROW,
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReconciliationDelta:
    """A single per-key delta between snapshot and current emissions."""

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
    threshold_pct_used: Decimal = Decimal("5")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Full reconciliation between a snapshot and current consolidated state."""

    total_prior: Decimal
    total_current: Decimal
    total_abs_delta: Decimal
    total_delta_pct: Decimal | None
    rows: tuple[ReconciliationDelta, ...]
    material_count: int
    restatement_required: bool
    cause_breakdown: Mapping[str, Decimal] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
_ZERO = Decimal("0")


def _as_decimal(v: Any) -> Decimal | None:
    """Coerce a JSON-ish value to Decimal.  None passes through."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    # str() then Decimal() -- avoids float-binary contamination of
    # caller-supplied numbers (NUMERIC(18,6) is Decimal in the API).
    return Decimal(str(v))


def _key(row: Mapping[str, Any]) -> tuple[int, str, str | None, int]:
    """Build the natural reconciliation key."""
    return (
        int(row["scope"]),
        str(row["sub_scope"]),
        row.get("codice_sito"),
        int(row["anno"]),
    )


def _pct(prior: Decimal | None, current: Decimal | None) -> Decimal | None:
    """Return (current - prior) / prior * 100, or None when undefined."""
    if prior is None or prior == _ZERO:
        return None
    cur = current if current is not None else _ZERO
    return (cur - prior) / prior * Decimal("100")


def _infer_cause(
    prior: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    methodology_flagged: bool,
) -> str:
    """Apply the cause-inference ladder.

    Precedence (first match wins):
      1. methodology_flagged    -> 'methodology'         (annotation-driven)
      2. prior missing          -> 'new_row'
      3. current missing        -> 'withdrawn_row'
      4. factor_version differs -> 'factor_update'
      5. both present, no factor_version change -> 'data_correction'
      6. fallback               -> 'unknown'
    """
    if methodology_flagged:
        return CAUSE_METHODOLOGY
    if prior is None and current is not None:
        return CAUSE_NEW_ROW
    if current is None and prior is not None:
        return CAUSE_WITHDRAWN_ROW
    if prior is not None and current is not None:
        p_v = prior.get("factor_version")
        c_v = current.get("factor_version")
        if p_v != c_v:
            return CAUSE_FACTOR_UPDATE
        return CAUSE_DATA_CORRECTION
    return CAUSE_UNKNOWN


# ---------------------------------------------------------------------------
# Public reconcile() entry point
# ---------------------------------------------------------------------------
def reconcile(
    *,
    snapshot_emissions: Iterable[Mapping[str, Any]],
    current_emissions: Iterable[Mapping[str, Any]],
    materiality_pct: Decimal = Decimal("5"),
    materiality_tco2e: Decimal = Decimal("100"),
    methodology_flags: Iterable[tuple[int, str, str | None, int]] = (),
    historical_by_year: Mapping[int, Mapping[tuple, Decimal]] | None = None,
) -> ReconciliationResult:
    """Compare two emission sets keyed on (scope, sub_scope, codice_sito, anno).

    Args:
        snapshot_emissions: Iterable of dict-like rows from the frozen
            snapshot.  Each row MUST contain ``scope``, ``sub_scope``,
            ``codice_sito``, ``anno``, ``tco2e``.  Optional: ``factor_id``,
            ``factor_version``, ``gwp_set``.
        current_emissions: Iterable of dict-like rows from the current
            consolidated state.  Same required keys as ``snapshot_emissions``.
        materiality_pct: Per-row materiality threshold (percent).  Default 5%
            mirrors GHG Protocol Chapter 5 and CSRD Article 23 convention.
        materiality_tco2e: Per-row floor in absolute tCO2e to ignore tiny
            denominators that would otherwise trip on noise.
        methodology_flags: External annotation channel.  Iterable of
            reconciliation keys flagged as methodology-driven; cause inference
            assigns ``methodology`` to these even when factor_version is equal.
        historical_by_year: Optional outer mapping keyed by year, inner
            mapping keyed by (scope, sub_scope, codice_sito) -> tco2e.
            When >= 3 historical YoY deltas can be derived per key
            (i.e. >= 4 years), the per-key historical sigma replaces
            ``materiality_pct`` as the per-row threshold.  The
            aggregate restatement gate still uses ``materiality_pct``
            as a global floor; the per-row sigma threshold can only flag
            MORE rows as material, never fewer.

    Returns:
        ReconciliationResult with totals, per-row deltas, material count,
        restatement_required flag, and a cause_breakdown by abs_delta.
    """
    prior_by_key: dict[tuple[int, str, str | None, int], Mapping[str, Any]] = {}
    current_by_key: dict[tuple[int, str, str | None, int], Mapping[str, Any]] = {}

    for row in snapshot_emissions:
        prior_by_key[_key(row)] = row
    for row in current_emissions:
        current_by_key[_key(row)] = row

    methodology_set = {tuple(k) for k in methodology_flags}

    # Build per-key (scope, sub_scope, codice_sito) historical sigma baseline.
    # The reconciliation row key includes anno, but historical_by_year is
    # year-indexed at the outer level, so we collapse the row key to its
    # first three elements when looking up baselines.
    baseline_by_key3: dict[tuple, Any] = {}
    if historical_by_year:
        normalised: dict[int, dict[tuple, Decimal]] = {}
        for y, inner in historical_by_year.items():
            normalised[int(y)] = {
                tuple(k): (v if isinstance(v, Decimal) else Decimal(str(v)))
                for k, v in inner.items()
            }
        baseline_by_key3 = compute_yoy_baseline(normalised)  # type: ignore[assignment]

    all_keys = sorted(set(prior_by_key) | set(current_by_key))

    rows: list[ReconciliationDelta] = []
    total_prior = _ZERO
    total_current = _ZERO
    material_count = 0
    cause_breakdown: dict[str, Decimal] = {c: _ZERO for c in ALL_CAUSES}

    # 2x materiality_pct gate for "single row tripping restatement" --
    # matches CSRD Article 23 convention that a single material item
    # > 2 * normal threshold is itself restatement-worthy.
    single_row_threshold = materiality_pct * Decimal("2")
    any_single_row_tripped = False

    for k in all_keys:
        prior_row = prior_by_key.get(k)
        cur_row = current_by_key.get(k)

        prior_tco2e = _as_decimal(prior_row.get("tco2e")) if prior_row else None
        current_tco2e = _as_decimal(cur_row.get("tco2e")) if cur_row else None

        # Math: None treated as 0 for delta arithmetic.
        prior_math = prior_tco2e if prior_tco2e is not None else _ZERO
        current_math = current_tco2e if current_tco2e is not None else _ZERO
        abs_delta = current_math - prior_math

        total_prior += prior_math
        total_current += current_math

        pct_delta = _pct(prior_tco2e, current_tco2e)

        cause = _infer_cause(
            prior_row, cur_row, methodology_flagged=(k in methodology_set)
        )

        # Per-row pct threshold.  When a reliable sigma baseline is
        # available for (scope, sub_scope, codice_sito), use it; otherwise
        # fall back to ``materiality_pct``.  The sigma threshold can only
        # be LOWER than the fallback in some cases (very stable history)
        # which flags MORE rows as material -- consistent with the spec
        # "can only flag MORE rows, never fewer".  When the sigma is
        # higher than the fallback we still clamp DOWN to materiality_pct
        # to honour the floor.
        key3 = (k[0], k[1], k[2])
        baseline = baseline_by_key3.get(key3)
        if baseline is not None and getattr(baseline, "is_reliable", False):
            sigma_thr = threshold_pct(
                baseline, fallback_pct=materiality_pct
            )
            row_threshold = min(sigma_thr, materiality_pct)
        else:
            row_threshold = materiality_pct

        # Materiality: per-row threshold combines pct AND absolute floor to
        # filter the case where a small base value produces a huge % swing
        # on negligible tCO2e.
        material = (
            pct_delta is not None
            and abs(pct_delta) > row_threshold
            and abs(abs_delta) >= materiality_tco2e
        ) or (
            # New / withdrawn rows count as material when they breach the
            # absolute floor (no prior pct is defined for these).
            pct_delta is None and abs(abs_delta) >= materiality_tco2e
        )
        if material:
            material_count += 1

        # Restatement trigger #2: any single row exceeds 2x normal threshold
        # AND breaches the absolute floor.
        if (
            pct_delta is not None
            and abs(pct_delta) > single_row_threshold
            and abs(abs_delta) >= materiality_tco2e
        ):
            any_single_row_tripped = True

        cause_breakdown[cause] = cause_breakdown.get(cause, _ZERO) + abs(abs_delta)

        rows.append(
            ReconciliationDelta(
                scope=k[0],
                sub_scope=k[1],
                codice_sito=k[2],
                anno=k[3],
                prior_tco2e=prior_tco2e,
                current_tco2e=current_tco2e,
                abs_delta=abs_delta,
                pct_delta=pct_delta,
                cause_category=cause,
                material=material,
                threshold_pct_used=row_threshold,
            )
        )

    # Aggregate pct delta -- None if prior was zero (avoids div/0).
    total_delta_pct: Decimal | None
    if total_prior == _ZERO:
        total_delta_pct = None
    else:
        total_delta_pct = (total_current - total_prior) / total_prior * Decimal("100")

    # Restatement: aggregate over threshold OR any single sub_scope row
    # tripped the 2x gate.
    aggregate_trip = (
        total_delta_pct is not None and abs(total_delta_pct) > materiality_pct
    )
    restatement_required = aggregate_trip or any_single_row_tripped

    logger.info(
        "reconciliation_completed",
        total_prior=str(total_prior),
        total_current=str(total_current),
        total_delta_pct=str(total_delta_pct) if total_delta_pct is not None else None,
        material_count=material_count,
        restatement_required=restatement_required,
    )

    return ReconciliationResult(
        total_prior=total_prior,
        total_current=total_current,
        total_abs_delta=total_current - total_prior,
        total_delta_pct=total_delta_pct,
        rows=tuple(rows),
        material_count=material_count,
        restatement_required=restatement_required,
        cause_breakdown=cause_breakdown,
    )
