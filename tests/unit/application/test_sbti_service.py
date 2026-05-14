"""Unit tests for the SBTi trajectory + status service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ghg_tool.application.services.sbti_service import (
    TargetStatus,
    annotate_actuals,
    assess_status,
    compute_trajectory,
)
from ghg_tool.domain.entities.sbti_target import SbtiTarget


def _make_target(**overrides: object) -> SbtiTarget:
    """Build an SbtiTarget with defaults; overrides allow per-test tweaks."""
    base: dict[str, object] = {
        "target_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "name": "Test 1.5C target",
        "scope_coverage": "S1+S2_LB",
        "baseline_year": 2020,
        "baseline_tco2e": Decimal("100.000"),
        "target_year": 2030,
        "target_tco2e": Decimal("58.000"),
        "reduction_pct": Decimal("42.00"),
        "alignment": "1.5C",
        "methodology": "SBTi_ACA",
        "sbti_approval_status": "validated",
        "sbti_validation_date": None,
        "created_by": "test-user",
        "created_at": datetime.now(UTC),
        "is_active": True,
    }
    base.update(overrides)
    if base["sbti_approval_status"] == "validated" and base["sbti_validation_date"] is None:
        from datetime import date as _date
        base["sbti_validation_date"] = _date(2024, 1, 1)
    return SbtiTarget(**base)  # type: ignore[arg-type]


class TestComputeTrajectory:
    def test_endpoints_are_exact(self) -> None:
        pts = compute_trajectory(
            baseline_year=2020,
            baseline_tco2e=Decimal("100"),
            target_year=2030,
            target_tco2e=Decimal("58"),
        )
        assert pts[0].year == 2020
        assert pts[0].trajectory_tco2e == Decimal("100")
        assert pts[-1].year == 2030
        assert pts[-1].trajectory_tco2e == Decimal("58")
        assert len(pts) == 11  # inclusive of both endpoints

    def test_linear_step_decimal(self) -> None:
        pts = compute_trajectory(
            baseline_year=2020,
            baseline_tco2e=Decimal("100"),
            target_year=2030,
            target_tco2e=Decimal("0"),
        )
        # Annual step is 10 tCO2e for a 100-to-0 linear path over 10 years.
        assert pts[1].trajectory_tco2e == Decimal("90")
        assert pts[5].trajectory_tco2e == Decimal("50")

    def test_rejects_target_year_before_baseline(self) -> None:
        with pytest.raises(ValueError):
            compute_trajectory(
                baseline_year=2025, baseline_tco2e=Decimal("100"),
                target_year=2020, target_tco2e=Decimal("50"),
            )

    def test_rejects_negative_target_tco2e(self) -> None:
        with pytest.raises(ValueError):
            compute_trajectory(
                baseline_year=2020, baseline_tco2e=Decimal("100"),
                target_year=2030, target_tco2e=Decimal("-1"),
            )


class TestAssessStatus:
    def test_on_track_when_actual_matches_trajectory(self) -> None:
        target = _make_target()
        # Trajectory @ 2024 with 100->58 over 2020-2030 is 100-(4.2*4) = 83.2
        status = assess_status(
            target=target,
            actual_by_year={2024: Decimal("83.2")},
        )
        assert status is TargetStatus.ON_TRACK

    def test_on_track_within_5_pct_band(self) -> None:
        target = _make_target()
        # 5% above trajectory
        traj_2024 = Decimal("83.2")
        actual = traj_2024 * Decimal("1.05")
        status = assess_status(
            target=target, actual_by_year={2024: actual},
        )
        assert status is TargetStatus.ON_TRACK

    def test_slightly_off(self) -> None:
        target = _make_target()
        traj_2024 = Decimal("83.2")
        actual = traj_2024 * Decimal("1.07")  # 7% above
        status = assess_status(
            target=target, actual_by_year={2024: actual},
        )
        assert status is TargetStatus.SLIGHTLY_OFF

    def test_off_track(self) -> None:
        target = _make_target()
        traj_2024 = Decimal("83.2")
        actual = traj_2024 * Decimal("1.15")  # 15% above
        status = assess_status(
            target=target, actual_by_year={2024: actual},
        )
        assert status is TargetStatus.OFF_TRACK

    def test_no_data_when_empty(self) -> None:
        target = _make_target()
        status = assess_status(target=target, actual_by_year={})
        assert status is TargetStatus.NO_DATA

    def test_uses_latest_year_with_data(self) -> None:
        target = _make_target()
        status = assess_status(
            target=target,
            actual_by_year={
                2020: Decimal("100"),
                2021: Decimal("96"),
                2024: Decimal("83.2"),  # on-track at 2024
            },
        )
        assert status is TargetStatus.ON_TRACK


class TestAnnotateActuals:
    def test_populates_only_known_years(self) -> None:
        traj = compute_trajectory(
            baseline_year=2020,
            baseline_tco2e=Decimal("100"),
            target_year=2025,
            target_tco2e=Decimal("50"),
        )
        annotated = annotate_actuals(traj, {2020: Decimal("100"), 2022: Decimal("82")})
        by_year = {pt.year: pt.actual_tco2e for pt in annotated}
        assert by_year[2020] == Decimal("100")
        assert by_year[2021] is None
        assert by_year[2022] == Decimal("82")
        assert by_year[2025] is None
