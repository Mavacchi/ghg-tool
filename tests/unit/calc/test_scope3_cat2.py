"""Unit tests for scope3_cat2_capital_goods (FR-10)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat2_capital_goods
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _s3_row(
    *, sottocategoria: str, quantita: str = "100000", anno: int = 2024,
    categoria_s3: int = 2,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": quantita,
        "anno": anno,
        "categoria_s3": categoria_s3,
    }


def test_impiantistica(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat2_capital_goods.calculate(
        [_s3_row(sottocategoria="Impiantistica")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    # 0.40 × 100000 × 0.001 = 40 t
    assert out[0].tco2e == Decimal("40.000")
    assert out[0].sub_scope == "Cat2"


def test_materiali_consumo(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat2_capital_goods.calculate(
        [_s3_row(sottocategoria="Materiali di consumo")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].tco2e == Decimal("32.000")


def test_unknown_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat2_capital_goods.calculate(
        [_s3_row(sottocategoria="Mystery")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_non_cat2_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat2_capital_goods.calculate(
        [_s3_row(sottocategoria="Impiantistica", categoria_s3=3)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _s3_row(sottocategoria="Impiantistica")
    row["id"] = str(row["id"])
    out = scope3_cat2_capital_goods.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _s3_row(sottocategoria="Impiantistica")
    row["id"] = None
    out = scope3_cat2_capital_goods.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None
