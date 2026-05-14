"""Unit tests for scope1_fugitive_zero.calculate (FR-35, MG-18)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope1_fugitive_zero
from tests.unit.calc.conftest import InMemoryFactorCatalog

SITES = (
    "IANO", "VIANO", "VIANO_GARGOLA",
    "CASALGRANDE", "FIORANO", "SASSUOLO", "FRASSINORO",
)


def test_one_zero_row_per_site(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_fugitive_zero.calculate(
        SITES, catalog, ar6_gwp,
        anno=2024, correlation_id=correlation_id, created_by="t",
    )
    assert len(out) == 7
    assert {r.codice_sito for r in out} == set(SITES)


def test_each_row_has_zero_tco2e(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_fugitive_zero.calculate(
        SITES, catalog, ar6_gwp,
        anno=2024, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.tco2e == Decimal("0") for r in out)


def test_raw_row_id_is_none_for_synth(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_fugitive_zero.calculate(
        SITES, catalog, ar6_gwp,
        anno=2024, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.raw_row_id is None for r in out)


def test_rationale_in_disclosure_notes(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_fugitive_zero.calculate(
        SITES, catalog, ar6_gwp,
        anno=2024, correlation_id=correlation_id, created_by="t",
    )
    note = out[0].disclosure_notes or ""
    assert "OI-10" in note
    assert "Closed-loop" in note


def test_sub_scope_fugitive_and_methodology(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_fugitive_zero.calculate(
        SITES, catalog, ar6_gwp,
        anno=2025, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.sub_scope == "fugitive" for r in out)
    assert all(r.methodology == "declared-zero" for r in out)
    assert all(r.anno == 2025 for r in out)


def test_ar5_path_stamps_correct_gwp_set(
    catalog: InMemoryFactorCatalog, ar5_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope1_fugitive_zero.calculate(
        SITES, catalog, ar5_gwp,
        anno=2024, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.gwp_set == "AR5" for r in out)
