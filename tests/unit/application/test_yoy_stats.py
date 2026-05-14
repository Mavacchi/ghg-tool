"""Unit tests for the shared yoy_stats helper (Decimal-end-to-end).

The helper computes per-key historical YoY-delta sigma and exposes
``threshold_pct`` for hot-spot and reconciliation services to share a
single statistical convention.
"""

from __future__ import annotations

from decimal import Decimal

from ghg_tool.application.services.yoy_stats import (
    YoYStatsBaseline,
    compute_yoy_baseline,
    threshold_pct,
)


def test_empty_input_returns_empty_dict() -> None:
    """No history at all -> no baselines."""
    assert compute_yoy_baseline({}) == {}


def test_three_years_gives_two_deltas_not_reliable() -> None:
    """3 years -> 2 YoY deltas; reliability needs >= 3 deltas (4 years)."""
    key = (3, "Cat1", None)
    history = {
        2022: {key: Decimal("100")},
        2023: {key: Decimal("110")},
        2024: {key: Decimal("121")},
    }
    out = compute_yoy_baseline(history)
    assert key in out
    bl = out[key]
    assert bl.sample_size == 2
    assert bl.is_reliable is False


def test_four_years_gives_three_deltas_reliable() -> None:
    """4 years -> 3 YoY deltas, sample passes the min_sample threshold."""
    key = (3, "Cat1", None)
    history = {
        2021: {key: Decimal("100")},
        2022: {key: Decimal("110")},
        2023: {key: Decimal("121")},
        2024: {key: Decimal("133.1")},
    }
    out = compute_yoy_baseline(history)
    bl = out[key]
    assert bl.sample_size == 3
    assert bl.is_reliable is True


def test_constant_yoy_yields_zero_sigma() -> None:
    """A perfectly constant +10% YoY must produce sigma_pct == 0."""
    key = (1, "comb", "A")
    history = {
        2020: {key: Decimal("100")},
        2021: {key: Decimal("110")},
        2022: {key: Decimal("121")},
        2023: {key: Decimal("133.1")},
    }
    out = compute_yoy_baseline(history)
    bl = out[key]
    assert bl.is_reliable is True
    # Each YoY delta is exactly 10%, so the std-dev is 0.
    assert bl.sigma_pct == Decimal("0")
    # Mean should be 10 (allowing trailing float-to-Decimal precision).
    assert abs(bl.mean_pct - Decimal("10")) < Decimal("0.0000001")


def test_missing_year_skips_transition() -> None:
    """A key missing from intermediate years simply skips those deltas."""
    key = (2, "elec_LB", "S1")
    history = {
        2020: {key: Decimal("100")},
        # 2021 missing -> 2020->2021 and 2021->2022 transitions skipped
        2022: {key: Decimal("110")},
        2023: {key: Decimal("121")},
    }
    out = compute_yoy_baseline(history)
    bl = out[key]
    # Only one valid transition: 2022->2023 (=10%).
    assert bl.sample_size == 1
    assert bl.is_reliable is False
    assert bl.mean_pct == Decimal("10")


def test_threshold_returns_fallback_when_none() -> None:
    """threshold_pct(None) -> fallback."""
    assert threshold_pct(None) == Decimal("20")
    assert threshold_pct(None, fallback_pct=Decimal("33")) == Decimal("33")


def test_threshold_returns_fallback_when_not_reliable() -> None:
    """Baseline with sample_size < min_sample yields the fallback."""
    bl = YoYStatsBaseline(
        key=("k",),
        sample_size=2,
        mean_pct=Decimal("5"),
        sigma_pct=Decimal("3"),
        is_reliable=False,
    )
    assert threshold_pct(bl) == Decimal("20")


def test_threshold_returns_mean_plus_two_sigma_when_reliable() -> None:
    """|mean| + 2 * sigma is returned when the baseline is reliable."""
    bl = YoYStatsBaseline(
        key=("k",),
        sample_size=4,
        mean_pct=Decimal("3"),
        sigma_pct=Decimal("4"),
        is_reliable=True,
    )
    # |3| + 2*4 = 11
    assert threshold_pct(bl) == Decimal("11")


def test_threshold_uses_absolute_mean() -> None:
    """A negative mean YoY (declining trend) is still added in absolute value."""
    bl = YoYStatsBaseline(
        key=("k",),
        sample_size=4,
        mean_pct=Decimal("-5"),
        sigma_pct=Decimal("2"),
        is_reliable=True,
    )
    # |-5| + 2*2 = 9
    assert threshold_pct(bl) == Decimal("9")


def test_decimal_precision_preserved() -> None:
    """Verify the result type is Decimal across the entire surface (no float)."""
    key = (1, "comb", None)
    history = {
        2020: {key: Decimal("100.000000")},
        2021: {key: Decimal("105.500000")},
        2022: {key: Decimal("111.302500")},
        2023: {key: Decimal("117.424138")},
    }
    out = compute_yoy_baseline(history)
    bl = out[key]
    assert isinstance(bl.mean_pct, Decimal)
    assert isinstance(bl.sigma_pct, Decimal)
    thr = threshold_pct(bl)
    assert isinstance(thr, Decimal)
