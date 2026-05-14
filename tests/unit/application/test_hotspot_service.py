"""Unit tests for hotspot_service (Scope 3 Pareto hot-spot ranking)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from ghg_tool.application.services.hotspot_service import (
    CONCENTRATION_THRESHOLD,
    YOY_FALLBACK_PCT,
    HotspotEntry,
    compute_hotspots,
)
from ghg_tool.domain.entities.emission_record import EmissionRecord


def _em(
    *,
    sub_scope: str,
    tco2e: str,
    scope: int = 3,
    anno: int = 2025,
) -> EmissionRecord:
    """Factory: minimal EmissionRecord with valid invariants."""
    return EmissionRecord(
        correlation_id=uuid.uuid4(),
        raw_row_id=None,
        scope=scope,
        sub_scope=sub_scope,
        codice_sito=None,
        anno=anno,
        tco2e=Decimal(tco2e),
        factor_id="X",
        factor_version="1",
        factor_source="DEFRA",
        gwp_set="AR6",
        methodology="activity-based",
        regulatory_stream="CSRD_ESRS_E1",
        calc_timestamp=datetime.now(UTC),
        created_by="tester",
    )


def test_empty_current_returns_empty_list() -> None:
    """No Scope 3 input means no ranking."""
    assert compute_hotspots(emissions_current=[]) == []


def test_only_non_scope3_rows_filtered_out() -> None:
    """Scope 1/2 rows must be ignored entirely."""
    emissions = [
        _em(sub_scope="combustion", tco2e="500", scope=1),
        _em(sub_scope="LB", tco2e="300", scope=2),
    ]
    assert compute_hotspots(emissions_current=emissions) == []


def test_single_category_at_100_pct() -> None:
    """A single Scope 3 row yields one entry at 100% / cumulative 100%."""
    out = compute_hotspots(emissions_current=[_em(sub_scope="Cat1", tco2e="1000")])
    assert len(out) == 1
    entry = out[0]
    assert entry.rank == 1
    assert entry.sub_scope == "Cat1"
    assert entry.tco2e == Decimal("1000")
    assert entry.pct_of_scope3 == Decimal("100")
    assert entry.cumulative_pct == Decimal("100")
    assert entry.yoy_delta_pct is None


def test_pareto_60_30_10_split() -> None:
    """Three categories at 60/30/10 must yield cumulative 60, 90, 100."""
    emissions = [
        _em(sub_scope="Cat1", tco2e="600"),
        _em(sub_scope="Cat2", tco2e="300"),
        _em(sub_scope="Cat4", tco2e="100"),
    ]
    out = compute_hotspots(emissions_current=emissions)
    assert [e.sub_scope for e in out] == ["Cat1", "Cat2", "Cat4"]
    assert [e.pct_of_scope3 for e in out] == [
        Decimal("60"), Decimal("30"), Decimal("10"),
    ]
    assert [e.cumulative_pct for e in out] == [
        Decimal("60"), Decimal("90"), Decimal("100"),
    ]


def test_aggregates_duplicate_sub_scope_rows() -> None:
    """Multiple rows on the same sub_scope must be summed before ranking."""
    emissions = [
        _em(sub_scope="Cat1", tco2e="400"),
        _em(sub_scope="Cat1", tco2e="200"),
        _em(sub_scope="Cat2", tco2e="400"),
    ]
    out = compute_hotspots(emissions_current=emissions)
    cat1 = next(e for e in out if e.sub_scope == "Cat1")
    assert cat1.tco2e == Decimal("600")
    assert cat1.rank == 1


def test_flag_high_concentration_trips_when_top5_over_80_pct() -> None:
    """Top-5 carrying > 80% must trip flag_high_concentration on every entry."""
    # 6 categories: 5 large (100 total), 2 small -> top5 = 100/(100+4+1) = 95.2% > 80.
    big_subs = ["Cat1", "Cat2", "Cat4", "Cat5", "Cat6"]
    small_subs = ["Cat7", "Cat9"]
    emissions = [_em(sub_scope=s, tco2e="20") for s in big_subs]
    emissions.append(_em(sub_scope=small_subs[0], tco2e="4"))
    emissions.append(_em(sub_scope=small_subs[1], tco2e="1"))
    out = compute_hotspots(emissions_current=emissions)
    assert all(e.flag_high_concentration for e in out)


def test_flag_high_concentration_off_when_top5_below_threshold() -> None:
    """Even distribution across 7 categories must NOT trip the flag."""
    subs = ["Cat1", "Cat2", "Cat4", "Cat5", "Cat6", "Cat7", "Cat9"]
    emissions = [_em(sub_scope=s, tco2e="100") for s in subs]
    out = compute_hotspots(emissions_current=emissions)
    # top5 = 500/700 ~= 71.4% which is below the 80% threshold.
    assert CONCENTRATION_THRESHOLD == Decimal("80")
    assert not any(e.flag_high_concentration for e in out)


def test_yoy_delta_computed_when_prior_supplied() -> None:
    """Cat1: 600 prior -> 900 current must yield +50% YoY delta."""
    current = [_em(sub_scope="Cat1", tco2e="900", anno=2025)]
    prior = [_em(sub_scope="Cat1", tco2e="600", anno=2024)]
    out = compute_hotspots(emissions_current=current, emissions_prior=prior)
    assert out[0].yoy_delta_pct == Decimal("50")


def test_yoy_outlier_flag_above_fallback_threshold() -> None:
    """A +50% YoY delta exceeds the +/- 20% single-prior-year fallback."""
    current = [_em(sub_scope="Cat1", tco2e="900", anno=2025)]
    prior = [_em(sub_scope="Cat1", tco2e="600", anno=2024)]
    out = compute_hotspots(emissions_current=current, emissions_prior=prior)
    assert abs(out[0].yoy_delta_pct or Decimal("0")) > YOY_FALLBACK_PCT
    assert out[0].flag_yoy_outlier is True


def test_yoy_outlier_flag_off_within_fallback_threshold() -> None:
    """A +10% YoY delta is within the +/- 20% fallback band."""
    current = [_em(sub_scope="Cat1", tco2e="660", anno=2025)]
    prior = [_em(sub_scope="Cat1", tco2e="600", anno=2024)]
    out = compute_hotspots(emissions_current=current, emissions_prior=prior)
    assert out[0].yoy_delta_pct == Decimal("10")
    assert out[0].flag_yoy_outlier is False


def test_prior_only_categories_not_included_in_output() -> None:
    """Sub_scopes present in prior but missing from current must be dropped."""
    current = [_em(sub_scope="Cat1", tco2e="500", anno=2025)]
    prior = [
        _em(sub_scope="Cat1", tco2e="400", anno=2024),
        _em(sub_scope="Cat2", tco2e="999", anno=2024),
    ]
    out = compute_hotspots(emissions_current=current, emissions_prior=prior)
    assert [e.sub_scope for e in out] == ["Cat1"]


def test_current_only_categories_have_none_yoy() -> None:
    """Sub_scopes present in current but not in prior must have yoy=None."""
    current = [
        _em(sub_scope="Cat1", tco2e="500", anno=2025),
        _em(sub_scope="Cat2", tco2e="200", anno=2025),
    ]
    prior = [_em(sub_scope="Cat1", tco2e="400", anno=2024)]
    out = compute_hotspots(emissions_current=current, emissions_prior=prior)
    cat2 = next(e for e in out if e.sub_scope == "Cat2")
    assert cat2.yoy_delta_pct is None
    assert cat2.flag_yoy_outlier is False


def test_top_n_truncates_output() -> None:
    """top_n=3 must return at most 3 entries, retaining the largest ones."""
    # Pairs of (sub_scope, tco2e) ordered so the descending ranking is fixed.
    pairs = [
        ("Cat1", "900"),
        ("Cat2", "800"),
        ("Cat4", "700"),
        ("Cat5", "600"),
        ("Cat6", "500"),
    ]
    emissions = [_em(sub_scope=s, tco2e=v) for s, v in pairs]
    out = compute_hotspots(emissions_current=emissions, top_n=3)
    assert len(out) == 3
    assert [e.rank for e in out] == [1, 2, 3]
    assert [e.sub_scope for e in out] == ["Cat1", "Cat2", "Cat4"]


def test_category_label_mirrors_pdf_builder() -> None:
    """category_label must match the IT mapping used by the PDF builder."""
    from ghg_tool.ui.pdf.builder import _S3_CAT_NAMES
    out = compute_hotspots(emissions_current=[_em(sub_scope="Cat1", tco2e="100")])
    assert out[0].category_label == _S3_CAT_NAMES["Cat1"]


def test_output_is_immutable() -> None:
    """HotspotEntry is frozen: assignment must raise."""
    out = compute_hotspots(emissions_current=[_em(sub_scope="Cat1", tco2e="100")])
    entry: HotspotEntry = out[0]
    import dataclasses
    try:
        entry.rank = 999  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("HotspotEntry should be frozen")
