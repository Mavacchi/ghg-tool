"""Unit tests for ``calc_orchestrator`` service.

Verifies the 16-module sequence wiring and the MG-10 single-GWP-set check.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.services.calc_orchestrator import (
    CalcOrchestrator,
    CalcRunInputs,
    _sigma_scope1_from_rows,
    _sigma_scope2_from_rows,
)
from tests.unit.calc.conftest import InMemoryFactorCatalog  # noqa: F401 — reused via fixture chain

SITES = (
    "IANO", "VIANO", "VIANO_GARGOLA",
    "CASALGRANDE", "FIORANO", "SASSUOLO", "FRASSINORO",
)


def _s1_row(
    codice_sito: str = "IANO", combustibile: str = "GAS_NAT",
    quantita: str = "1000", anno: int = 2024,
    categoria: str = "Combustione stazionaria",
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "codice_sito": codice_sito,
        "combustibile": combustibile,
        "quantita": quantita,
        "anno": anno,
        "categoria_s1": categoria,
    }


def _s2_row(
    codice_sito: str = "IANO", quantita: str = "1000000",
    strumento_mb: str | None = "Grid_Residual", anno: int = 2024,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "codice_sito": codice_sito,
        "quantita": quantita,
        "anno": anno,
        "voce_s2": "EE_Acquistata_Grid",
        "strumento_mb": strumento_mb,
    }


def _s3_row(
    *, categoria_s3: int = 1, sottocategoria: str = "Argille",
    quantita: str = "1000", anno: int = 2024,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "categoria_s3": categoria_s3,
        "sottocategoria": sottocategoria,
        "quantita": quantita,
        "anno": anno,
    }


def test_orchestrator_full_run_produces_all_categories(
    catalog, ar6_gwp,
) -> None:
    inputs = CalcRunInputs(
        correlation_id=uuid.uuid4(),
        anno=2024,
        sites=SITES,
        scope1_rows=(_s1_row(),),
        scope2_rows=(_s2_row(),),
        scope3_rows=(
            _s3_row(categoria_s3=1, sottocategoria="Argille"),
            _s3_row(categoria_s3=2, sottocategoria="Impiantistica"),
            _s3_row(categoria_s3=4, sottocategoria="Argille_Strada"),
            _s3_row(categoria_s3=5, sottocategoria="Discarica non pericolosi"),
            _s3_row(categoria_s3=6, sottocategoria="Voli"),
            _s3_row(categoria_s3=7, sottocategoria="Commuting_Auto"),
            _s3_row(categoria_s3=9, sottocategoria="Italia_Strada"),
            _s3_row(categoria_s3=12, sottocategoria="EOL_Piastrelle"),
        ),
    )
    out = CalcOrchestrator(catalog, ar6_gwp).run(inputs)

    sub_scopes = {r.sub_scope for r in out}
    # All 16 module families represented
    expected = {
        "fugitive", "combustion",
        "LB", "MB",
        "Cat1", "Cat2",
        "Cat3_WTT_FUEL", "Cat3_WTT_ELEC", "Cat3_TND",
        "Cat4", "Cat5", "Cat6", "Cat7", "Cat9", "Cat12",
        "Cat11_ZERO",
        "Cat8_ZERO", "Cat10_ZERO", "Cat13_ZERO", "Cat14_ZERO", "Cat15_ZERO",
    }
    assert expected.issubset(sub_scopes)


def test_orchestrator_emits_fugitive_zero_per_site(catalog, ar6_gwp) -> None:
    inputs = CalcRunInputs(
        correlation_id=uuid.uuid4(),
        anno=2024,
        sites=SITES,
        scope1_rows=(),
        scope2_rows=(),
        scope3_rows=(),
    )
    out = CalcOrchestrator(catalog, ar6_gwp).run(inputs)
    fugitive = [r for r in out if r.sub_scope == "fugitive"]
    assert len(fugitive) == 7
    assert all(r.tco2e == Decimal("0") for r in fugitive)


def test_orchestrator_process_emitted_for_iano(catalog, ar6_gwp) -> None:
    inputs = CalcRunInputs(
        correlation_id=uuid.uuid4(),
        anno=2024,
        sites=("IANO",),
        scope1_rows=(_s1_row(
            codice_sito="IANO", combustibile="CACO3",
            quantita="10000", categoria="Processo_Decarb",
        ),),
        scope2_rows=(),
        scope3_rows=(),
    )
    out = CalcOrchestrator(catalog, ar6_gwp).run(inputs)
    process = [r for r in out if r.sub_scope == "process"]
    assert len(process) == 1
    assert process[0].tco2e == Decimal("4397.0000")


def test_sigma_scope1_excludes_process_rows() -> None:
    rows = [
        _s1_row(combustibile="GAS_NAT", quantita="100", anno=2024),
        _s1_row(combustibile="GAS_NAT", quantita="200", anno=2024),
        _s1_row(combustibile="CACO3", quantita="999", anno=2024,
                categoria="Processo_Decarb"),
    ]
    sigma = _sigma_scope1_from_rows(rows)
    assert sigma[("GAS_NAT", 2024)] == Decimal("300")
    assert ("CACO3", 2024) not in sigma


def test_sigma_scope2_aggregates_by_year() -> None:
    rows = [
        _s2_row(quantita="100", anno=2024),
        _s2_row(quantita="200", anno=2024),
        _s2_row(quantita="50", anno=2025),
    ]
    sigma = _sigma_scope2_from_rows(rows)
    assert sigma[2024] == Decimal("300")
    assert sigma[2025] == Decimal("50")


def test_orchestrator_uses_sigma_for_cat3(catalog, ar6_gwp) -> None:
    inputs = CalcRunInputs(
        correlation_id=uuid.uuid4(),
        anno=2024,
        sites=("IANO",),
        scope1_rows=(
            _s1_row(combustibile="GAS_NAT", quantita="1000", anno=2024),
            _s1_row(combustibile="GAS_NAT", quantita="2000", anno=2024,
                    codice_sito="VIANO"),
        ),
        scope2_rows=(_s2_row(quantita="500000"),),
        scope3_rows=(),
    )
    out = CalcOrchestrator(catalog, ar6_gwp).run(inputs)
    wtt_gas_nat = [
        r for r in out
        if r.sub_scope == "Cat3_WTT_FUEL" and "GAS_NAT" in r.factor_id
    ]
    assert len(wtt_gas_nat) == 1
    # Σ Scope 1 GAS_NAT 2024 = 3000 × 0.029 × 0.001 = 0.087
    assert wtt_gas_nat[0].tco2e == Decimal("0.087")


def test_orchestrator_single_gwp_set_invariant(catalog, ar6_gwp) -> None:
    """Cross-check that every emitted row uses the same gwp_set."""
    inputs = CalcRunInputs(
        correlation_id=uuid.uuid4(), anno=2024, sites=SITES,
        scope1_rows=(), scope2_rows=(), scope3_rows=(),
    )
    out = CalcOrchestrator(catalog, ar6_gwp).run(inputs)
    assert {r.gwp_set for r in out} == {"AR6"}


def test_orchestrator_eu_ets_dual_track(catalog, ar5_gwp) -> None:
    """AR5 path tags regulatory_stream='EU_ETS_PHASE_IV'."""
    inputs = CalcRunInputs(
        correlation_id=uuid.uuid4(), anno=2024,
        sites=SITES, scope1_rows=(), scope2_rows=(), scope3_rows=(),
        regulatory_stream="EU_ETS_PHASE_IV",
    )
    out = CalcOrchestrator(catalog, ar5_gwp).run(inputs)
    assert all(r.gwp_set == "AR5" for r in out)
    assert all(r.regulatory_stream == "EU_ETS_PHASE_IV" for r in out)
