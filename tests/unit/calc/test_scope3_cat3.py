"""Unit tests for scope3_cat3_fuel_energy (FR-11, MG-05)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from ghg_tool.application.calc import scope3_cat3_fuel_energy
from ghg_tool.domain.exceptions.calc_errors import MissingFactorError
from tests.unit.calc.conftest import InMemoryFactorCatalog


def test_fuel_wtt_per_combustibile_year(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    sigma_s1 = {
        ("GAS_NAT", 2024): Decimal("1000"),
        ("GAS_NAT", 2025): Decimal("1200"),
        ("GASOLIO", 2024): Decimal("500"),
    }
    out = scope3_cat3_fuel_energy.calculate(
        sigma_scope1=sigma_s1,
        sigma_scope2_kwh={},
        factors=catalog,
        gwp=ar6_gwp,
        correlation_id=correlation_id,
        created_by="t",
    )
    fuel_records = [r for r in out if r.sub_scope == "Cat3_WTT_FUEL"]
    assert len(fuel_records) == 3
    expected = {
        ("GAS_NAT", 2024): Decimal("0.029") * Decimal("1000") * Decimal("0.001"),
        ("GAS_NAT", 2025): Decimal("0.029") * Decimal("1200") * Decimal("0.001"),
        ("GASOLIO", 2024): Decimal("0.029") * Decimal("500") * Decimal("0.001"),
    }
    # factor_id is like "WTT_GAS_NAT_DEFRA_2025" — match the GAS_NAT/2024 case
    for r in fuel_records:
        if "GAS_NAT" in r.factor_id and r.anno == 2024:
            assert r.tco2e == expected[("GAS_NAT", 2024)]


def test_electricity_wtt_per_year(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat3_fuel_energy.calculate(
        sigma_scope1={},
        sigma_scope2_kwh={2024: Decimal("1000000")},
        factors=catalog,
        gwp=ar6_gwp,
        correlation_id=correlation_id,
        created_by="t",
    )
    wtt = [r for r in out if r.sub_scope == "Cat3_WTT_ELEC"]
    tnd = [r for r in out if r.sub_scope == "Cat3_TND"]
    assert len(wtt) == 1
    assert len(tnd) == 1
    # 1e6 × 0.022 × 0.001 = 22 t WTT
    assert wtt[0].tco2e == Decimal("22.000")
    # 1e6 × 0.017 × 0.001 = 17 t T&D
    assert tnd[0].tco2e == Decimal("17.000")


def test_zero_sigma_scope1_empty_fuel_records(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat3_fuel_energy.calculate(
        sigma_scope1={},
        sigma_scope2_kwh={},
        factors=catalog,
        gwp=ar6_gwp,
        correlation_id=correlation_id,
        created_by="t",
    )
    assert out == []


def test_unknown_combustibile_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat3_fuel_energy.calculate(
        sigma_scope1={("UNKNOWN", 2024): Decimal("1000")},
        sigma_scope2_kwh={},
        factors=catalog,
        gwp=ar6_gwp,
        correlation_id=correlation_id,
        created_by="t",
    )
    assert out == []


def test_methodology_activity_based(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat3_fuel_energy.calculate(
        sigma_scope1={("GAS_NAT", 2024): Decimal("1000")},
        sigma_scope2_kwh={2024: Decimal("1000")},
        factors=catalog,
        gwp=ar6_gwp,
        correlation_id=correlation_id,
        created_by="t",
    )
    assert all(r.methodology == "activity-based" for r in out)


def test_disclosure_calls_out_fr11_rule(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat3_fuel_energy.calculate(
        sigma_scope1={("GAS_NAT", 2024): Decimal("1000")},
        sigma_scope2_kwh={},
        factors=catalog,
        gwp=ar6_gwp,
        correlation_id=correlation_id,
        created_by="t",
    )
    assert "FR-11" in (out[0].disclosure_notes or "")


# ---------------------------------------------------------------------------
# REQUIRED: WTT_ELEC upstream factor absent
# ---------------------------------------------------------------------------

def test_missing_wtt_elec_factor_raises(
    ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    """Raises MissingFactorError when WTT_ELEC_DEFRA_2025 is absent from catalog.

    The catalog is seeded without 'WTT_ELEC_DEFRA_2025' so that calling
    calculate() with sigma_scope2_kwh non-empty triggers MissingFactorError.

    Per domain policy, a missing upstream electricity WTT factor must block
    the calculation rather than silently produce zero emissions.
    """
    catalog_without_wtt_elec = InMemoryFactorCatalog(seed={})

    with pytest.raises(MissingFactorError):
        scope3_cat3_fuel_energy.calculate(
            sigma_scope1={},
            sigma_scope2_kwh={2024: Decimal("1000000")},
            factors=catalog_without_wtt_elec,
            gwp=ar6_gwp,
            correlation_id=correlation_id,
            created_by="t",
        )


def test_wtt_elec_absent_with_empty_scope2_still_raises(
    ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    """MissingFactorError raises even with empty sigma_scope2_kwh.

    Implementation note: _electricity_wtt_records calls require_factor
    unconditionally before the inner loop, so the lookup always fires
    regardless of whether sigma_scope2_kwh is empty.  This means that a
    catalog without WTT_ELEC_DEFRA_2025 will raise even on empty input.
    Documented as expected behaviour — the caller must always provide a
    complete factor catalog.
    """
    catalog_without_wtt_elec = InMemoryFactorCatalog(seed={})

    with pytest.raises(MissingFactorError):
        scope3_cat3_fuel_energy.calculate(
            sigma_scope1={},
            sigma_scope2_kwh={},  # empty but factor lookup still fires
            factors=catalog_without_wtt_elec,
            gwp=ar6_gwp,
            correlation_id=correlation_id,
            created_by="t",
        )
