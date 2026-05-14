"""Unit tests for scope3_cat6_business_travel (FR-14, bootstrap CI)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat6_business_travel
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _row(
    *, sottocategoria: str, quantita: str = "10000", anno: int = 2024,
    categoria_s3: int = 6,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": quantita,
        "anno": anno,
        "categoria_s3": categoria_s3,
    }


def test_voli_factor_resolved(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat6_business_travel.calculate(
        [_row(sottocategoria="Voli internazionali")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "TRAVEL_SPEND_FLIGHTS_DEFRA_2025"


def test_auto_noleggio_resolved(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat6_business_travel.calculate(
        [_row(sottocategoria="Auto noleggio business")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "TRAVEL_SPEND_HIRECAR_DEFRA_2025"


def test_hotel_resolved(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat6_business_travel.calculate(
        [_row(sottocategoria="Hotel stays UK")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].factor_id == "TRAVEL_SPEND_HOTEL_DEFRA_2025"


def test_uncertainty_band_populated(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat6_business_travel.calculate(
        [_row(sottocategoria="Voli internazionali", quantita="10000")],
        catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    assert rec.uncertainty_band_lower is not None
    assert rec.uncertainty_band_upper is not None
    # Lower must be < upper
    assert rec.uncertainty_band_lower < rec.uncertainty_band_upper
    # Both bounds non-negative
    assert rec.uncertainty_band_lower >= Decimal("0")
    # Upper > point estimate is plausible; lower < point estimate
    assert rec.uncertainty_band_lower <= rec.tco2e <= rec.uncertainty_band_upper * Decimal("2")


def test_uncertainty_zero_for_zero_spend(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat6_business_travel.calculate(
        [_row(sottocategoria="Voli", quantita="0")],
        catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].uncertainty_band_lower == Decimal("0")
    assert out[0].uncertainty_band_upper == Decimal("0")


def test_bootstrap_is_deterministic(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    """Same input twice → same uncertainty bounds (fixed seed)."""
    row = _row(sottocategoria="Voli", quantita="10000")
    out1 = scope3_cat6_business_travel.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    out2 = scope3_cat6_business_travel.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out1[0].uncertainty_band_lower == out2[0].uncertainty_band_lower
    assert out1[0].uncertainty_band_upper == out2[0].uncertainty_band_upper


def test_unknown_subcategory_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat6_business_travel.calculate(
        [_row(sottocategoria="Train tickets")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_non_cat6_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat6_business_travel.calculate(
        [_row(sottocategoria="Voli", categoria_s3=7)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_disclosure_mentions_bootstrap(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat6_business_travel.calculate(
        [_row(sottocategoria="Voli")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert "bootstrap" in (out[0].disclosure_notes or "")


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row(sottocategoria="Voli")
    row["id"] = str(row["id"])
    out = scope3_cat6_business_travel.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row(sottocategoria="Voli")
    row["id"] = None
    out = scope3_cat6_business_travel.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None
