"""Unit tests for scope3_cat7_commuting (FR-15)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat7_commuting
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _row(
    *, sottocategoria: str = "Commuting_Auto",
    quantita: str = "4452800", anno: int = 2024,
    categoria_s3: int = 7,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "sottocategoria": sottocategoria,
        "quantita": quantita,
        "anno": anno,
        "categoria_s3": categoria_s3,
    }


def test_commuting_auto_applied(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat7_commuting.calculate(
        [_row()], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    # 0.17 × 4452800 × 0.001 = 756.976 t
    assert out[0].tco2e == Decimal("756.976000")
    assert out[0].sub_scope == "Cat7"
    assert out[0].methodology == "distance-based"


def test_fte_in_disclosure(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat7_commuting.calculate(
        [_row(anno=2024)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert "FTE=506" in (out[0].disclosure_notes or "")
    out2 = scope3_cat7_commuting.calculate(
        [_row(anno=2025)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert "FTE=484" in (out2[0].disclosure_notes or "")


def test_unknown_year_fte_label(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat7_commuting.calculate(
        [_row(anno=2099)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert "FTE=n/a" in (out[0].disclosure_notes or "")


def test_non_commuting_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat7_commuting.calculate(
        [_row(sottocategoria="Other transport")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_non_cat7_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat7_commuting.calculate(
        [_row(categoria_s3=8)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row()
    row["id"] = str(row["id"])
    out = scope3_cat7_commuting.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row()
    row["id"] = None
    out = scope3_cat7_commuting.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None
