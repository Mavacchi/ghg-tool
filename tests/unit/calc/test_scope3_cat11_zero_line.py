"""Unit tests for scope3_cat11_zero_line (FR-18, MG-06)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat11_zero_line
from tests.unit.calc.conftest import InMemoryFactorCatalog


def test_one_zero_line_per_call(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat11_zero_line.calculate(
        catalog, ar6_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    assert len(out) == 1
    assert out[0].tco2e == Decimal("0")
    assert out[0].sub_scope == "Cat11_ZERO"


def test_immaterial_rationale(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat11_zero_line.calculate(
        catalog, ar6_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    note = out[0].disclosure_notes or ""
    assert "Immaterial" in note
    assert "passive products" in note


def test_methodology_declared_zero(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat11_zero_line.calculate(
        catalog, ar6_gwp, anno=2025,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].methodology == "declared-zero"
    assert out[0].anno == 2025


def test_ar5_path(
    catalog: InMemoryFactorCatalog, ar5_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat11_zero_line.calculate(
        catalog, ar5_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].gwp_set == "AR5"


def test_raw_row_id_none(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat11_zero_line.calculate(
        catalog, ar6_gwp, anno=2024,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None
