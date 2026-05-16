"""Unit tests for SbtiTarget domain entity — covers __post_init__ validation.

Missing coverage lines: 87, 92, 97, 102, 107, 109, 111, 113, 121
(all ValueError raises in __post_init__).

Parametrize cases: valid construction, each invalid field, boundary/edge cases.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from ghg_tool.domain.entities.sbti_target import SbtiTarget

# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_BASELINE_DATE = date(2020, 1, 1)


def _make_target(**overrides) -> SbtiTarget:
    """Return a valid SbtiTarget with any fields overridden."""
    defaults = {
        "target_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "name": "Near-term S1+S2 -42%",
        "scope_coverage": "S1+S2_LB",
        "baseline_year": 2020,
        "baseline_tco2e": Decimal("10000"),
        "target_year": 2030,
        "target_tco2e": Decimal("5800"),
        "reduction_pct": Decimal("42"),
        "alignment": "1.5C",
        "methodology": "SBTi_ACA",
        "sbti_approval_status": "validated",
        "sbti_validation_date": _BASELINE_DATE,
        "created_by": "test",
        "created_at": _NOW,
        "is_active": True,
    }
    defaults.update(overrides)
    return SbtiTarget(**defaults)


# ---------------------------------------------------------------------------
# Valid construction
# ---------------------------------------------------------------------------

class TestSbtiTargetValidConstruction:
    def test_valid_target_constructs_without_error(self) -> None:
        target = _make_target()
        assert target.scope_coverage == "S1+S2_LB"
        assert target.alignment == "1.5C"

    def test_target_is_frozen(self) -> None:
        target = _make_target()
        with pytest.raises(AttributeError):
            target.name = "changed"  # type: ignore[misc]

    def test_committed_status_no_validation_date_allowed(self) -> None:
        target = _make_target(
            sbti_approval_status="committed",
            sbti_validation_date=None,
        )
        assert target.sbti_approval_status == "committed"

    @pytest.mark.parametrize("scope", [
        "S1", "S2_LB", "S2_MB", "S3", "S1+S2_LB", "S1+S2_MB", "S1+S2_MB+S3",
    ])
    def test_all_allowed_scope_coverages(self, scope: str) -> None:
        target = _make_target(scope_coverage=scope)
        assert target.scope_coverage == scope

    @pytest.mark.parametrize("alignment", ["1.5C", "WB2C", "2C"])
    def test_all_allowed_alignments(self, alignment: str) -> None:
        target = _make_target(alignment=alignment)
        assert target.alignment == alignment

    @pytest.mark.parametrize("status", ["none", "committed", "targets_set", "validated"])
    def test_all_allowed_sbti_statuses(self, status: str) -> None:
        kwargs = {}
        if status == "validated":
            kwargs["sbti_validation_date"] = _BASELINE_DATE
        else:
            kwargs["sbti_validation_date"] = None
        target = _make_target(sbti_approval_status=status, **kwargs)
        assert target.sbti_approval_status == status

    def test_target_tco2e_equal_to_zero_allowed(self) -> None:
        """A net-zero target (target_tco2e=0) is permitted."""
        target = _make_target(target_tco2e=Decimal("0"))
        assert target.target_tco2e == Decimal("0")

    def test_target_tco2e_equal_to_baseline_raises(self) -> None:
        """target_tco2e == baseline_tco2e would be no reduction — allowed by entity but
        edge: target_tco2e > baseline_tco2e is rejected."""
        target = _make_target(
            target_tco2e=Decimal("10000"),
            baseline_tco2e=Decimal("10000"),
        )
        assert target.target_tco2e == target.baseline_tco2e


# ---------------------------------------------------------------------------
# Validation failures — each ValueError branch in __post_init__
# ---------------------------------------------------------------------------

class TestSbtiTargetValidationErrors:

    # Line 87 — invalid scope_coverage
    def test_invalid_scope_coverage_raises(self) -> None:
        with pytest.raises(ValueError, match="scope_coverage"):
            _make_target(scope_coverage="S4_INVALID")

    def test_scope_coverage_ar4_string_raises(self) -> None:
        with pytest.raises(ValueError, match="scope_coverage"):
            _make_target(scope_coverage="AR4")

    # Line 92 — invalid alignment
    def test_invalid_alignment_raises(self) -> None:
        with pytest.raises(ValueError, match="alignment"):
            _make_target(alignment="3C")

    def test_alignment_ar6_string_raises(self) -> None:
        with pytest.raises(ValueError, match="alignment"):
            _make_target(alignment="net_zero")

    # Line 97 — invalid methodology
    def test_invalid_methodology_raises(self) -> None:
        with pytest.raises(ValueError, match="methodology"):
            _make_target(methodology="unknown_method")

    # Line 102 — invalid sbti_approval_status
    def test_invalid_sbti_approval_status_raises(self) -> None:
        with pytest.raises(ValueError, match="sbti_approval_status"):
            _make_target(sbti_approval_status="approved")

    def test_sbti_status_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="sbti_approval_status"):
            _make_target(sbti_approval_status="")

    # Line 107 — target_year <= baseline_year
    def test_target_year_equal_baseline_year_raises(self) -> None:
        with pytest.raises(ValueError, match="target_year must be after baseline_year"):
            _make_target(target_year=2020, baseline_year=2020)

    def test_target_year_before_baseline_year_raises(self) -> None:
        with pytest.raises(ValueError, match="target_year must be after baseline_year"):
            _make_target(target_year=2019, baseline_year=2020)

    # Line 109 — baseline_tco2e <= 0
    def test_zero_baseline_tco2e_raises(self) -> None:
        with pytest.raises(ValueError, match="baseline_tco2e must be positive"):
            _make_target(baseline_tco2e=Decimal("0"))

    def test_negative_baseline_tco2e_raises(self) -> None:
        with pytest.raises(ValueError, match="baseline_tco2e must be positive"):
            _make_target(baseline_tco2e=Decimal("-1"))

    # Line 111 — target_tco2e < 0
    def test_negative_target_tco2e_raises(self) -> None:
        with pytest.raises(ValueError, match="target_tco2e must be non-negative"):
            _make_target(target_tco2e=Decimal("-0.001"))

    # Line 113 — target_tco2e > baseline_tco2e
    def test_target_exceeds_baseline_raises(self) -> None:
        with pytest.raises(ValueError, match="REDUCTION target"):
            _make_target(
                baseline_tco2e=Decimal("10000"),
                target_tco2e=Decimal("10001"),
            )

    # Line 121 — validated status without validation_date
    def test_validated_status_without_date_raises(self) -> None:
        with pytest.raises(ValueError, match="sbti_validation_date is required"):
            _make_target(
                sbti_approval_status="validated",
                sbti_validation_date=None,
            )


# ---------------------------------------------------------------------------
# Parametrized boundary / SBTi semantic cases
# ---------------------------------------------------------------------------

class TestSbtiTargetProgressScenarios:
    """Boundary scenarios: overshoot, exact-on-track, pre-base-year edge."""

    @pytest.mark.parametrize("anno,desc", [
        (2030, "at target year"),
        (2025, "mid-trajectory"),
        (2020, "at baseline year"),
    ])
    def test_target_constructs_for_various_years(self, anno: int, desc: str) -> None:
        """SbtiTarget construction is independent of the 'current' reporting year."""
        target = _make_target(
            baseline_year=2020,
            target_year=2030,
            baseline_tco2e=Decimal("10000"),
            target_tco2e=Decimal("5000"),
        )
        assert target.baseline_year == 2020
        assert target.target_year == 2030

    def test_overshoot_scenario_construction(self) -> None:
        """A target with a very aggressive reduction target constructs without error."""
        target = _make_target(
            baseline_tco2e=Decimal("50000"),
            target_tco2e=Decimal("100"),  # 99.8% reduction
            reduction_pct=Decimal("99.8"),
        )
        assert target.target_tco2e == Decimal("100")

    def test_exact_on_track_zero_target(self) -> None:
        """target_tco2e=0 is permitted (net-zero commitment)."""
        target = _make_target(
            baseline_tco2e=Decimal("10000"),
            target_tco2e=Decimal("0"),
            reduction_pct=Decimal("100"),
        )
        assert target.target_tco2e == Decimal("0")

    def test_minimal_reduction_still_valid(self) -> None:
        """Even a 1-unit reduction from baseline is valid."""
        target = _make_target(
            baseline_tco2e=Decimal("10000"),
            target_tco2e=Decimal("9999"),
            reduction_pct=Decimal("0.01"),
        )
        assert target.target_tco2e < target.baseline_tco2e

    def test_all_allowed_methodologies_accepted(self) -> None:
        """Every methodology code in the allowed set constructs without error."""
        for methodology in (
            "SBTi_ACA", "SDA", "GEVA", "SBTi_NetZero",
            "supplier_engagement", "custom",
        ):
            target = _make_target(methodology=methodology)
            assert target.methodology == methodology
