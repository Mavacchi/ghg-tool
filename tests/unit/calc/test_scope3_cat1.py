"""Unit tests for scope3_cat1_purchased_goods (FR-09, ADR-007)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat1_purchased_goods
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _s3_row(
    *, sottocategoria: str, quantita: str = "1000", anno: int = 2024,
    categoria_s3: int = 1,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": quantita,
        "anno": anno,
        "categoria_s3": categoria_s3,
    }


def test_argille_mass_based(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Argille")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    # 0.5 kg CO2e / kg × 1000 kg × 0.001 = 0.5 t
    assert out[0].tco2e == Decimal("0.500")
    assert out[0].methodology == "mass-based"


def test_servizi_vari_spend_based(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Servizi vari", quantita="10000")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    # 0.25 × 10000 × 0.001 = 2.5 t
    assert out[0].tco2e == Decimal("2.500")
    assert out[0].methodology == "spend-based"


def test_cardboard_biogenic_split(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Imballaggi cartone", quantita="1000")],
        catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    # Factor 1.2 kg CO2e/kg × 1000 kg × 0.001 = 1.2 t fossil+nonCO2 GWP-weighted total
    assert rec.tco2e == Decimal("1.200")
    assert rec.co2_fossil_tonne == Decimal("1.200")
    # Biogenic share 0.8 × 1000 kg × 0.001 = 0.8 t biogenic memo
    assert rec.co2_biogenic_tonne == Decimal("0.800")


def test_pallet_biogenic_split(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Pallet legno", quantita="500")],
        catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    rec = out[0]
    assert rec.tco2e == Decimal("0.300")  # 0.6 × 500 × 0.001
    assert rec.co2_biogenic_tonne == Decimal("0.200")  # 0.4 × 500 × 0.001


def test_unknown_subcategory_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Mystery material")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_non_cat1_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Argille", categoria_s3=2)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_codice_sito_none_for_cat1(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Argille")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].codice_sito is None


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _s3_row(sottocategoria="Argille")
    row["id"] = str(row["id"])
    out = scope3_cat1_purchased_goods.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _s3_row(sottocategoria="Argille")
    row["id"] = None
    out = scope3_cat1_purchased_goods.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None


def test_disclosure_notes_includes_biogenic_marker(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Imballaggi cartone")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert "ADR-007" in (out[0].disclosure_notes or "")


def test_no_biogenic_when_share_is_none(
    factor_seed: dict[tuple[str, str], object], ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    """If catalog returns biogenic_share=None, the columns remain None."""
    from tests.unit.calc.conftest import _factor
    seed = dict(factor_seed)
    seed[("ECOINV_CARDBOARD_V3_10", "AR6")] = _factor(
        "ECOINV_CARDBOARD_V3_10", "1.2",
        unit="kg CO2e / kg", source="ecoinvent v3.10",
        gwp_set="AR6", biogenic=None,
    )
    cat = InMemoryFactorCatalog(seed)
    out = scope3_cat1_purchased_goods.calculate(
        [_s3_row(sottocategoria="Imballaggi cartone")], cat, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].co2_biogenic_tonne is None
    assert out[0].co2_fossil_tonne is None
