"""Unit tests for intensity_service (KPI-09/10/11, FR-25)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from ghg_tool.application.services.intensity_service import (
    IntensityReferenceInputs,
    compute_intensities,
)
from ghg_tool.domain.entities.emission_record import EmissionRecord


def _em(
    *, scope: int, sub_scope: str, anno: int = 2024,
    tco2e: str = "100", gwp_set: str = "AR6",
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> EmissionRecord:
    return EmissionRecord(
        correlation_id=uuid.uuid4(),
        raw_row_id=None,
        scope=scope,
        sub_scope=sub_scope,
        codice_sito=None,
        anno=anno,
        tco2e=Decimal(tco2e),
        factor_id="X", factor_version="1", factor_source="DEFRA",
        gwp_set=gwp_set,
        methodology="activity-based",
        regulatory_stream=regulatory_stream,
        calc_timestamp=datetime.now(UTC),
        created_by="tester",
    )


def test_intensity_returns_three_kpis_x_two_variants_x_n_years() -> None:
    emissions = [
        _em(scope=1, sub_scope="combustion", tco2e="1000"),
        _em(scope=2, sub_scope="LB", tco2e="500"),
        _em(scope=2, sub_scope="MB", tco2e="200"),
        _em(scope=3, sub_scope="Cat1", tco2e="300"),
    ]
    ref = [IntensityReferenceInputs(
        anno=2024,
        production_tonnes=Decimal("10000"),
        revenue_meur=Decimal("100"),
        fte=506,
    )]
    out = compute_intensities(
        emissions, ref,
        correlation_id=uuid.uuid4(),
        gwp_set="AR6",
    )
    # 3 KPIs × 2 variants × 1 year = 6
    assert len(out) == 6


def test_lb_vs_mb_numerators_differ() -> None:
    emissions = [
        _em(scope=1, sub_scope="combustion", tco2e="1000"),
        _em(scope=2, sub_scope="LB", tco2e="500"),
        _em(scope=2, sub_scope="MB", tco2e="0"),
        _em(scope=3, sub_scope="Cat1", tco2e="300"),
    ]
    ref = [IntensityReferenceInputs(
        anno=2024,
        production_tonnes=Decimal("100"),
        revenue_meur=Decimal("10"),
        fte=100,
    )]
    out = compute_intensities(emissions, ref,
                              correlation_id=uuid.uuid4(), gwp_set="AR6")
    lb_kpi09 = next(r for r in out if r.kpi_code == "KPI-09" and r.scope2_variant == "LB")
    mb_kpi09 = next(r for r in out if r.kpi_code == "KPI-09" and r.scope2_variant == "MB")
    # LB total = 1000 + 500 + 300 = 1800; intensity = 18.0
    assert lb_kpi09.intensity_value == Decimal("18")
    # MB total = 1000 + 0 + 300 = 1300; intensity = 13.0
    assert mb_kpi09.intensity_value == Decimal("13")


def test_filters_by_gwp_set() -> None:
    emissions = [
        _em(scope=1, sub_scope="combustion", tco2e="1000", gwp_set="AR6"),
        _em(scope=1, sub_scope="combustion", tco2e="9999", gwp_set="AR5"),
        _em(scope=2, sub_scope="LB", tco2e="500", gwp_set="AR6"),
    ]
    ref = [IntensityReferenceInputs(
        anno=2024, production_tonnes=Decimal("100"),
        revenue_meur=Decimal("10"), fte=100,
    )]
    out = compute_intensities(emissions, ref,
                              correlation_id=uuid.uuid4(), gwp_set="AR6")
    lb_kpi09 = next(r for r in out if r.kpi_code == "KPI-09" and r.scope2_variant == "LB")
    # Only AR6 sum: 1000 + 500 = 1500; intensity = 15.0
    assert lb_kpi09.intensity_value == Decimal("15")


def test_kpi_codes_complete() -> None:
    emissions = [_em(scope=1, sub_scope="combustion", tco2e="100")]
    ref = [IntensityReferenceInputs(
        anno=2024, production_tonnes=Decimal("100"),
        revenue_meur=Decimal("10"), fte=100,
    )]
    out = compute_intensities(emissions, ref,
                              correlation_id=uuid.uuid4(), gwp_set="AR6")
    assert {r.kpi_code for r in out} == {"KPI-09", "KPI-10", "KPI-11"}


def test_filters_by_regulatory_stream() -> None:
    emissions = [
        _em(scope=1, sub_scope="combustion", tco2e="1000",
            regulatory_stream="CSRD_ESRS_E1"),
        _em(scope=1, sub_scope="combustion", tco2e="9999",
            regulatory_stream="EU_ETS_PHASE_IV"),
    ]
    ref = [IntensityReferenceInputs(
        anno=2024, production_tonnes=Decimal("100"),
        revenue_meur=Decimal("10"), fte=100,
    )]
    out = compute_intensities(emissions, ref,
                              correlation_id=uuid.uuid4(),
                              gwp_set="AR6",
                              regulatory_stream="CSRD_ESRS_E1")
    lb09 = next(r for r in out if r.kpi_code == "KPI-09" and r.scope2_variant == "LB")
    assert lb09.numerator_tco2e == Decimal("1000")


def test_explicit_timestamp_override() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    emissions = [_em(scope=1, sub_scope="combustion", tco2e="100")]
    ref = [IntensityReferenceInputs(
        anno=2024, production_tonnes=Decimal("100"),
        revenue_meur=Decimal("10"), fte=100,
    )]
    out = compute_intensities(
        emissions, ref, correlation_id=uuid.uuid4(),
        gwp_set="AR6", calc_timestamp=ts,
    )
    assert all(r.calc_timestamp == ts for r in out)


def test_fte_disclosure_note_present() -> None:
    emissions = [_em(scope=1, sub_scope="combustion", tco2e="100")]
    ref = [IntensityReferenceInputs(
        anno=2024, production_tonnes=Decimal("100"),
        revenue_meur=Decimal("10"), fte=506,
    )]
    out = compute_intensities(emissions, ref,
                              correlation_id=uuid.uuid4(), gwp_set="AR6")
    kpi11 = next(r for r in out if r.kpi_code == "KPI-11")
    assert "FTE=506" in (kpi11.disclosure_notes or "")
