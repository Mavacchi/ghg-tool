"""Unit tests for scope3_cat4_upstream_transport (FR-12)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat4_upstream_transport
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _row(
    *, sottocategoria: str, quantita: str = "1000", anno: int = 2024,
    categoria_s3: int = 4,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": quantita,
        "anno": anno,
        "categoria_s3": categoria_s3,
    }


def test_road_uses_hgv_factor(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat4_upstream_transport.calculate(
        [_row(sottocategoria="Argille_Strada")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    # 0.106 × 1000 × 0.001 = 0.106 t
    assert out[0].tco2e == Decimal("0.1060000")
    assert out[0].factor_id == "FREIGHT_HGV_DEFRA_2025"


def test_rail(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat4_upstream_transport.calculate(
        [_row(sottocategoria="Feldspati_Treno")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "FREIGHT_RAIL_DEFRA_2025"


def test_sea(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat4_upstream_transport.calculate(
        [_row(sottocategoria="Import_Nave")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "FREIGHT_SEA_DEFRA_2025"


def test_zero_tkm_yields_zero(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat4_upstream_transport.calculate(
        [_row(sottocategoria="Feldspati_Treno", quantita="0")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].tco2e == Decimal("0E-7")  # exact 0 to inner precision


def test_unknown_mode_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat4_upstream_transport.calculate(
        [_row(sottocategoria="Carrier mystery mode")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_non_cat4_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat4_upstream_transport.calculate(
        [_row(sottocategoria="Argille_Strada", categoria_s3=5)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row(sottocategoria="Argille_Strada")
    row["id"] = str(row["id"])
    out = scope3_cat4_upstream_transport.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row(sottocategoria="Argille_Strada")
    row["id"] = None
    out = scope3_cat4_upstream_transport.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None
