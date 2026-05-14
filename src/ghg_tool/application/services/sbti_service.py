"""Science-Based Targets initiative (SBTi) trajectory + status service.

Implements the absolute-contraction (ACA) linear trajectory between
baseline and target year and assesses on-track / off-track status by
comparing actuals to the trajectory.

Pure-function service: no DB, no FastAPI, no Streamlit. The caller
loads the SbtiTarget and the actual_by_year mapping; this module just
computes.

Normative reference: ESRS E1-4 Disclosure Requirement on GHG emission
reduction targets; SBTi Corporate Net-Zero Standard v1.2 (2024)
absolute contraction approach (~4.2 %/yr for 1.5C aligned cross-sector).

Status thresholds (5 % / 10 %) are project conventions documented in
docs/methodology.md, not SBTi-defined.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ghg_tool.domain.entities.sbti_target import SbtiTarget


class TargetStatus(str, Enum):
    """How the actual emissions compare to the SBTi trajectory.

    Thresholds: project-defined for traffic-light UX, NOT SBTi-mandated.
      - ON_TRACK:      actual <= trajectory + 5%
      - SLIGHTLY_OFF:  trajectory + 5% < actual <= trajectory + 10%
      - OFF_TRACK:     actual > trajectory + 10%
      - NO_DATA:       no actual observations in the trajectory window
    """

    ON_TRACK = "ON_TRACK"
    SLIGHTLY_OFF = "SLIGHTLY_OFF"
    OFF_TRACK = "OFF_TRACK"
    NO_DATA = "NO_DATA"


@dataclass(frozen=True, slots=True)
class TrajectoryPoint:
    """One point on the SBTi target trajectory.

    Attributes:
        year: Calendar year on the trajectory.
        trajectory_tco2e: The straight-line target value at this year.
        actual_tco2e: Observed emissions at this year, or None if no
            actual is available.
    """

    year: int
    trajectory_tco2e: Decimal
    actual_tco2e: Decimal | None = None


def compute_trajectory(
    *,
    baseline_year: int,
    baseline_tco2e: Decimal,
    target_year: int,
    target_tco2e: Decimal,
) -> list[TrajectoryPoint]:
    """Return one TrajectoryPoint per year from baseline to target inclusive.

    Linear interpolation between (baseline_year, baseline_tco2e) and
    (target_year, target_tco2e). Endpoints are exact; intermediate
    years are computed with Decimal arithmetic (no float drift).

    Args:
        baseline_year: First year on the trajectory.
        baseline_tco2e: Emissions at baseline_year.
        target_year: Last year on the trajectory (must be > baseline_year).
        target_tco2e: Emissions at target_year (must be <= baseline_tco2e).

    Returns:
        Sorted list of TrajectoryPoint, with actual_tco2e=None until
        annotate_actuals() is called.

    Raises:
        ValueError: When target_year <= baseline_year or target_tco2e < 0.
    """
    if target_year <= baseline_year:
        raise ValueError("target_year must be after baseline_year")
    if target_tco2e < 0 or baseline_tco2e <= 0:
        raise ValueError("tco2e values must be positive")

    span = target_year - baseline_year
    delta_per_year = (baseline_tco2e - target_tco2e) / Decimal(span)
    points: list[TrajectoryPoint] = []
    for offset in range(span + 1):
        yr = baseline_year + offset
        if offset == 0:
            value = baseline_tco2e
        elif offset == span:
            value = target_tco2e
        else:
            value = baseline_tco2e - (delta_per_year * Decimal(offset))
        points.append(TrajectoryPoint(year=yr, trajectory_tco2e=value))
    return points


def annotate_actuals(
    trajectory: list[TrajectoryPoint],
    actual_by_year: dict[int, Decimal],
) -> list[TrajectoryPoint]:
    """Return a new list with actual_tco2e populated where data exists."""
    return [
        TrajectoryPoint(
            year=pt.year,
            trajectory_tco2e=pt.trajectory_tco2e,
            actual_tco2e=actual_by_year.get(pt.year),
        )
        for pt in trajectory
    ]


def _latest_year_with_data(actual_by_year: dict[int, Decimal]) -> int | None:
    """Return the most recent year that has an actual observation."""
    if not actual_by_year:
        return None
    return max(actual_by_year)


def assess_status(
    *,
    target: SbtiTarget,
    actual_by_year: dict[int, Decimal],
    on_track_band_pct: Decimal = Decimal("5"),
    slightly_off_band_pct: Decimal = Decimal("10"),
) -> TargetStatus:
    """Compare the latest actual against the trajectory point at that year.

    Args:
        target: The SBTi target dataclass.
        actual_by_year: Year -> observed tco2e mapping.
        on_track_band_pct: Percent above trajectory still counted ON_TRACK.
        slightly_off_band_pct: Percent above trajectory counted SLIGHTLY_OFF.

    Returns:
        TargetStatus reflecting the latest year for which actual data is
        available. Returns NO_DATA when actual_by_year is empty.
    """
    latest_year = _latest_year_with_data(actual_by_year)
    if latest_year is None:
        return TargetStatus.NO_DATA
    if latest_year < target.baseline_year:
        return TargetStatus.NO_DATA

    trajectory = compute_trajectory(
        baseline_year=target.baseline_year,
        baseline_tco2e=target.baseline_tco2e,
        target_year=target.target_year,
        target_tco2e=target.target_tco2e,
    )
    by_year = {pt.year: pt.trajectory_tco2e for pt in trajectory}
    traj_at_latest = by_year.get(latest_year)
    if traj_at_latest is None or traj_at_latest <= 0:
        return TargetStatus.NO_DATA

    actual = actual_by_year[latest_year]
    delta_pct = (actual - traj_at_latest) / traj_at_latest * Decimal("100")

    if delta_pct <= on_track_band_pct:
        return TargetStatus.ON_TRACK
    if delta_pct <= slightly_off_band_pct:
        return TargetStatus.SLIGHTLY_OFF
    return TargetStatus.OFF_TRACK
