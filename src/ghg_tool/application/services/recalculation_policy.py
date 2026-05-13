"""Recalculation-policy trigger — FR-26.

A structural change (acquisition / divestiture) or methodology change
causing a > 5% shift in base-year (2024) Scope 1 + 2 total tCO2e
triggers the mandatory base-year recalculation workflow.

This module is a pure-function policy evaluator: it takes two snapshot
totals (the old base-year total and the recomputed total) and returns
a structured ``RecalculationDecision`` indicating whether the threshold
was crossed and, if so, the policy metadata to attach to the notification
that the API layer ultimately raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# 5% threshold per FR-26 acceptance criterion
_THRESHOLD_PCT: Decimal = Decimal("0.05")
_BASE_YEAR: int = 2024


@dataclass(frozen=True, slots=True)
class RecalculationDecision:
    """Outcome of a recalculation-policy evaluation.

    Attributes:
        triggered: True if the recalculation workflow must launch.
        base_year: Always 2024 in this codebase.
        old_total_tco2e: Previous base-year Scope 1 + 2 total.
        new_total_tco2e: Newly recomputed base-year Scope 1 + 2 total.
        relative_delta: ``abs(new - old) / old`` as ``Decimal``; 0 when
            ``old_total_tco2e == 0`` (no division by zero — see invariant).
        threshold_pct: Fixed 5% policy threshold.
        reason_code: 'STRUCTURAL_CHANGE', 'METHODOLOGY_CHANGE', or None.
        notify_roles: Roles to notify (``('esg_manager', 'data_steward')`` when triggered).
    """

    triggered: bool
    base_year: int
    old_total_tco2e: Decimal
    new_total_tco2e: Decimal
    relative_delta: Decimal
    threshold_pct: Decimal
    reason_code: str | None
    notify_roles: tuple[str, ...]


def evaluate(
    *,
    old_total_tco2e: Decimal,
    new_total_tco2e: Decimal,
    reason_code: str | None = None,
) -> RecalculationDecision:
    """Evaluate whether the recalculation threshold was crossed.

    Args:
        old_total_tco2e: Previous base-year (2024) total Scope 1 + 2 tCO2e.
        new_total_tco2e: Newly recomputed total.
        reason_code: Caller-provided reason ('STRUCTURAL_CHANGE',
            'METHODOLOGY_CHANGE', etc.).  Required when triggered; the
            caller passes it through so the audit trail is preserved.

    Returns:
        ``RecalculationDecision`` describing the outcome.

    Raises:
        ValueError: If ``old_total_tco2e`` or ``new_total_tco2e`` is negative.
    """
    if old_total_tco2e < Decimal("0"):
        raise ValueError(f"old_total_tco2e must be >= 0; got {old_total_tco2e}")
    if new_total_tco2e < Decimal("0"):
        raise ValueError(f"new_total_tco2e must be >= 0; got {new_total_tco2e}")

    rel_delta = _relative_delta(old_total_tco2e, new_total_tco2e)
    triggered = rel_delta > _THRESHOLD_PCT
    return RecalculationDecision(
        triggered=triggered,
        base_year=_BASE_YEAR,
        old_total_tco2e=old_total_tco2e,
        new_total_tco2e=new_total_tco2e,
        relative_delta=rel_delta,
        threshold_pct=_THRESHOLD_PCT,
        reason_code=reason_code if triggered else None,
        notify_roles=("esg_manager", "data_steward") if triggered else (),
    )


def _relative_delta(old: Decimal, new: Decimal) -> Decimal:
    """Return ``abs(new - old) / old`` with 0/0 → 0 fallback.

    Args:
        old: Previous total.
        new: New total.

    Returns:
        ``Decimal`` relative delta.
    """
    if old == Decimal("0"):
        return Decimal("0") if new == Decimal("0") else Decimal("1")
    return abs(new - old) / old
