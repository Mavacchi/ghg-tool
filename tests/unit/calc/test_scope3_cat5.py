"""Unit tests for scope3_cat5_waste (FR-13)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat5_waste
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _row(
    *, sottocategoria: str, quantita: str = "100", anno: int = 2024,
    categoria_s3: int = 5,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": quantita,
        "anno": anno,
        "categoria_s3": categoria_s3,
    }


def test_landfill_non_pericolosi(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat5_waste.calculate(
        [_row(sottocategoria="Discarica non pericolosi")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "WASTE_LANDFILL_NONPERIC_DEFRA_2025"


def test_landfill_pericolosi(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat5_waste.calculate(
        [_row(sottocategoria="Discarica pericolosi")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "WASTE_LANDFILL_PERIC_DEFRA_2025"


def test_recycle_non_pericolosi(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat5_waste.calculate(
        [_row(sottocategoria="Riciclo non pericolosi")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "WASTE_RECYCLE_NONPERIC_DEFRA_2025"


def test_recycle_pericolosi(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat5_waste.calculate(
        [_row(sottocategoria="Riciclo pericolosi")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "WASTE_RECYCLE_PERIC_DEFRA_2025"


def test_unknown_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat5_waste.calculate(
        [_row(sottocategoria="Compostaggio sconosciuto")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_non_cat5_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat5_waste.calculate(
        [_row(sottocategoria="Discarica non pericolosi", categoria_s3=6)],
        catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_methodology_mass_based(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat5_waste.calculate(
        [_row(sottocategoria="Discarica non pericolosi")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].methodology == "mass-based"
    # 12.5 × 100 × 0.001 = 1.25 t
    assert out[0].tco2e == Decimal("1.2500")


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row(sottocategoria="Discarica non pericolosi")
    row["id"] = str(row["id"])
    out = scope3_cat5_waste.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row(sottocategoria="Discarica non pericolosi")
    row["id"] = None
    out = scope3_cat5_waste.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None
