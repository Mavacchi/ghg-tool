"""Unit tests for scope1_process.calculate (FR-06, MG-08, MG-09)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from ghg_tool.application.calc import scope1_process
from tests.unit.calc.conftest import InMemoryFactorCatalog, _factor


def _process_row(quantita: str = "10000", anno: int = 2024) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "combustibile": "CACO3",
        "quantita": quantita,
        "codice_sito": "IANO",
        "anno": anno,
        "categoria_s1": "Processo_Decarb",
    }


def test_stoichiometric_factor_applied(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_process.calculate(
        [_process_row("10000")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    # 0.4397 × 10000 = 4397 tCO2 exactly
    assert rec.co2_tonne == Decimal("4397.0000")
    assert rec.tco2e == Decimal("4397.0000")
    assert rec.ch4_tco2e is None
    assert rec.n2o_tco2e is None


def test_only_processo_decarb_rows_consumed(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    rows = [
        _process_row(),
        {**_process_row(), "categoria_s1": "Combustione stazionaria"},
    ]
    out = scope1_process.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert len(out) == 1


def test_sub_scope_and_methodology(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_process.calculate(
        [_process_row()], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].sub_scope == "process"
    assert out[0].methodology == "stoichiometric"


def test_loi_disclosure_note_present(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_process.calculate(
        [_process_row()], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert "LOI" in (out[0].disclosure_notes or "")
    assert "±10–20%" in (out[0].disclosure_notes or "")


def test_invariant_check_rejects_wrong_factor_value(
    factor_seed: dict[tuple[str, str], object], ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    seed = dict(factor_seed)
    # Inject a bad factor value
    seed[("STOICH_CACO3_IPCC_2006", "AR6")] = _factor(
        "STOICH_CACO3_IPCC_2006", "0.5", unit="t/t", source="IPCC", gwp_set="AR6",
    )
    bad_catalog = InMemoryFactorCatalog(seed)
    with pytest.raises(ValueError, match="0.4397"):
        scope1_process.calculate(
            [_process_row()], bad_catalog, ar6_gwp,
            correlation_id=correlation_id, created_by="t",
        )


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _process_row()
    row["id"] = str(row["id"])
    out = scope1_process.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id_yields_none_raw_row_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _process_row()
    row["id"] = None
    out = scope1_process.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None


def test_ar5_path_co2_invariant(
    catalog: InMemoryFactorCatalog, ar5_gwp, correlation_id: uuid.UUID,
) -> None:
    """AR5 vs AR6 — CO2 GWP is invariantly 1, so process tco2e is identical."""
    out6 = scope1_process.calculate(
        [_process_row()], catalog, __import__("ghg_tool.domain.ports.gwp_table",
        fromlist=["GWPSetTable"]).GWPSetTable(
            __import__("ghg_tool.domain.value_objects.gwp_set",
                       fromlist=["AR6"]).AR6
        ),
        correlation_id=correlation_id, created_by="t",
    )
    out5 = scope1_process.calculate(
        [_process_row()], catalog, ar5_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out6[0].tco2e == out5[0].tco2e
