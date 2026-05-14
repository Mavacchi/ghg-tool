"""Unit tests for scope3_cat_omitted_zero_lines (FR-36, MG-07)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat_omitted_zero_lines
from tests.unit.calc.conftest import InMemoryFactorCatalog


def test_five_rows_emitted(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat_omitted_zero_lines.calculate(
        catalog, ar6_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    assert len(out) == 5
    assert {r.sub_scope for r in out} == {
        "Cat8_ZERO", "Cat10_ZERO", "Cat13_ZERO", "Cat14_ZERO", "Cat15_ZERO",
    }


def test_each_zero_tco2e(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat_omitted_zero_lines.calculate(
        catalog, ar6_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    assert all(r.tco2e == Decimal("0") for r in out)


def test_methodology_declared_zero(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat_omitted_zero_lines.calculate(
        catalog, ar6_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    assert all(r.methodology == "declared-zero" for r in out)


def test_specific_rationales_present(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat_omitted_zero_lines.calculate(
        catalog, ar6_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    by_sub = {r.sub_scope: (r.disclosure_notes or "") for r in out}
    assert "leased assets" in by_sub["Cat8_ZERO"]
    assert "processing" in by_sub["Cat10_ZERO"].lower()
    assert "lessor" in by_sub["Cat13_ZERO"]
    assert "franchise" in by_sub["Cat14_ZERO"]
    assert "non-financial" in by_sub["Cat15_ZERO"]


def test_ar5_path(
    catalog: InMemoryFactorCatalog, ar5_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat_omitted_zero_lines.calculate(
        catalog, ar5_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    assert all(r.gwp_set == "AR5" for r in out)


def test_raw_row_id_none(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat_omitted_zero_lines.calculate(
        catalog, ar6_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    assert all(r.raw_row_id is None for r in out)
