"""Unit tests for scope1_combustion.calculate (FR-05)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from ghg_tool.application.calc import scope1_combustion
from ghg_tool.domain.exceptions.calc_errors import MissingFactorError
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _raw_row(
    *, combustibile: str = "GAS_NAT", quantita: str = "1000",
    codice_sito: str = "IANO", anno: int = 2024,
    categoria_s1: str = "Combustione stazionaria",
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "combustibile": combustibile,
        "quantita": quantita,
        "codice_sito": codice_sito,
        "anno": anno,
        "categoria_s1": categoria_s1,
    }


def test_gas_nat_three_components(
    catalog: InMemoryFactorCatalog,
    ar6_gwp,
    correlation_id: uuid.UUID,
) -> None:
    rows = [_raw_row(combustibile="GAS_NAT", quantita="1000")]
    out = scope1_combustion.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert len(out) == 1
    rec = out[0]
    # CO2 = 2.0 kg × 1000 = 2000 kg → 2.0 t
    assert rec.co2_tonne == Decimal("2.0")
    # CH4 in CO2e = 0.0001 × 1000 × 0.001 × 27.9 = 0.00279
    assert rec.ch4_tco2e == Decimal("0.00279")
    # N2O in CO2e = 0.00001 × 1000 × 0.001 × 273 = 0.00273
    assert rec.n2o_tco2e == Decimal("0.00273")
    assert rec.tco2e == rec.co2_tonne + rec.ch4_tco2e + rec.n2o_tco2e
    assert rec.scope == 1 and rec.sub_scope == "combustion"
    assert rec.co2_fossil_tonne == rec.co2_tonne


def test_gasolio_and_benzina_processed(
    catalog: InMemoryFactorCatalog,
    ar6_gwp,
    correlation_id: uuid.UUID,
) -> None:
    rows = [
        _raw_row(combustibile="GASOLIO", quantita="500"),
        _raw_row(combustibile="BENZINA", quantita="200"),
    ]
    out = scope1_combustion.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert {r.tco2e for r in out} == {
        Decimal("2.7") * Decimal("500") * Decimal("0.001")
        + Decimal("0.0002") * Decimal("500") * Decimal("0.001") * Decimal("27.9")
        + Decimal("0.00002") * Decimal("500") * Decimal("0.001") * Decimal("273"),
        Decimal("2.3") * Decimal("200") * Decimal("0.001")
        + Decimal("0.0003") * Decimal("200") * Decimal("0.001") * Decimal("27.9")
        + Decimal("0.00003") * Decimal("200") * Decimal("0.001") * Decimal("273"),
    }


def test_non_combustion_row_skipped(
    catalog: InMemoryFactorCatalog,
    ar6_gwp,
    correlation_id: uuid.UUID,
) -> None:
    rows = [_raw_row(combustibile="CACO3", categoria_s1="Processo_Decarb")]
    out = scope1_combustion.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_zero_quantity_still_emits_row(
    catalog: InMemoryFactorCatalog,
    ar6_gwp,
    correlation_id: uuid.UUID,
) -> None:
    rows = [_raw_row(combustibile="GAS_NAT", quantita="0")]
    out = scope1_combustion.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert len(out) == 1
    assert out[0].tco2e == Decimal("0")


def test_ar5_path_yields_different_non_co2(
    catalog: InMemoryFactorCatalog,
    ar5_gwp,
    correlation_id: uuid.UUID,
) -> None:
    rows = [_raw_row(combustibile="GAS_NAT", quantita="1000")]
    out = scope1_combustion.calculate(
        rows, catalog, ar5_gwp, correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    # AR5 CH4=28 (instead of 27.9), N2O=265 (instead of 273)
    assert rec.ch4_tco2e == Decimal("0.0001") * Decimal("1000") * Decimal("0.001") * Decimal("28")
    assert rec.n2o_tco2e == Decimal("0.00001") * Decimal("1000") * Decimal("0.001") * Decimal("265")
    assert rec.gwp_set == "AR5"


def test_string_id_coerced_to_uuid(
    catalog: InMemoryFactorCatalog,
    ar6_gwp,
    correlation_id: uuid.UUID,
) -> None:
    row = _raw_row()
    row["id"] = str(row["id"])
    out = scope1_combustion.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id_yields_none_raw_row_id(
    catalog: InMemoryFactorCatalog,
    ar6_gwp,
    correlation_id: uuid.UUID,
) -> None:
    row = _raw_row()
    row["id"] = None
    out = scope1_combustion.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None


def test_missing_factor_raises(
    catalog: InMemoryFactorCatalog,
    ar6_gwp,
    correlation_id: uuid.UUID,
) -> None:
    # Pop the GAS_NAT CO2 factor to trigger the missing-factor error
    catalog._seed.pop(("COMB_GAS_NAT_CO2_DEFRA_2025", "AR6"))  # noqa: SLF001
    rows = [_raw_row(combustibile="GAS_NAT")]
    with pytest.raises(MissingFactorError):
        scope1_combustion.calculate(
            rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
        )
