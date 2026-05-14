"""Unit tests for scope3_cat9_downstream_transport (FR-16)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat9_downstream_transport
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _row(
    *, sottocategoria: str, quantita: str = "1000", anno: int = 2024,
    categoria_s3: int = 9,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": quantita,
        "anno": anno,
        "categoria_s3": categoria_s3,
    }


def test_italia_strada_hgv(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat9_downstream_transport.calculate(
        [_row(sottocategoria="Italia_Strada")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "FREIGHT_HGV_DEFRA_2025"


def test_europa_strada_hgv(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat9_downstream_transport.calculate(
        [_row(sottocategoria="Europa_Strada")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "FREIGHT_HGV_DEFRA_2025"


def test_export_nave_sea(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat9_downstream_transport.calculate(
        [_row(sottocategoria="Export_Nave", quantita="5000")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "FREIGHT_SEA_DEFRA_2025"
    # 0.005 × 5000 × 0.001 = 0.025
    assert out[0].tco2e == Decimal("0.025000")


def test_load_factor_in_disclosure(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat9_downstream_transport.calculate(
        [_row(sottocategoria="Italia_Strada")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert "27 t" in (out[0].disclosure_notes or "")


def test_non_cat9_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat9_downstream_transport.calculate(
        [_row(sottocategoria="Italia_Strada", categoria_s3=8)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_unknown_mode_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat9_downstream_transport.calculate(
        [_row(sottocategoria="Mystery aviation")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row(sottocategoria="Italia_Strada")
    row["id"] = str(row["id"])
    out = scope3_cat9_downstream_transport.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row(sottocategoria="Italia_Strada")
    row["id"] = None
    out = scope3_cat9_downstream_transport.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None
