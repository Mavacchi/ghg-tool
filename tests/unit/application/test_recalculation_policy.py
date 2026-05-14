"""Unit tests for recalculation_policy.evaluate (FR-26)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ghg_tool.application.services.recalculation_policy import evaluate


def test_no_trigger_when_zero_delta() -> None:
    d = evaluate(old_total_tco2e=Decimal("1000"),
                 new_total_tco2e=Decimal("1000"))
    assert d.triggered is False
    assert d.relative_delta == Decimal("0")
    assert d.reason_code is None


def test_small_delta_below_threshold() -> None:
    """4% delta — below 5% threshold."""
    d = evaluate(old_total_tco2e=Decimal("1000"),
                 new_total_tco2e=Decimal("1040"))
    assert d.triggered is False
    assert d.relative_delta == Decimal("0.04")


def test_threshold_5_pct_not_triggered() -> None:
    """Exactly 5% — not triggered (must be strictly greater)."""
    d = evaluate(old_total_tco2e=Decimal("1000"),
                 new_total_tco2e=Decimal("1050"))
    assert d.triggered is False


def test_above_threshold_triggers() -> None:
    d = evaluate(old_total_tco2e=Decimal("1000"),
                 new_total_tco2e=Decimal("1100"),
                 reason_code="STRUCTURAL_CHANGE")
    assert d.triggered is True
    assert d.reason_code == "STRUCTURAL_CHANGE"
    assert d.notify_roles == ("esg_manager", "data_steward")


def test_decrease_above_threshold_triggers() -> None:
    """Decrease by 10% — also triggers."""
    d = evaluate(old_total_tco2e=Decimal("1000"),
                 new_total_tco2e=Decimal("900"),
                 reason_code="METHODOLOGY_CHANGE")
    assert d.triggered is True
    assert d.relative_delta == Decimal("0.1")


def test_zero_old_triggers_when_new_positive() -> None:
    d = evaluate(old_total_tco2e=Decimal("0"),
                 new_total_tco2e=Decimal("100"),
                 reason_code="STRUCTURAL_CHANGE")
    assert d.triggered is True
    assert d.relative_delta == Decimal("1")


def test_zero_to_zero_no_trigger() -> None:
    d = evaluate(old_total_tco2e=Decimal("0"),
                 new_total_tco2e=Decimal("0"))
    assert d.triggered is False
    assert d.relative_delta == Decimal("0")


def test_negative_inputs_rejected() -> None:
    with pytest.raises(ValueError, match="old_total"):
        evaluate(old_total_tco2e=Decimal("-1"), new_total_tco2e=Decimal("0"))
    with pytest.raises(ValueError, match="new_total"):
        evaluate(old_total_tco2e=Decimal("1"), new_total_tco2e=Decimal("-1"))


def test_decision_carries_base_year_2024() -> None:
    d = evaluate(old_total_tco2e=Decimal("1000"),
                 new_total_tco2e=Decimal("1000"))
    assert d.base_year == 2024


def test_threshold_pct_5_percent() -> None:
    d = evaluate(old_total_tco2e=Decimal("1000"),
                 new_total_tco2e=Decimal("1000"))
    assert d.threshold_pct == Decimal("0.05")
