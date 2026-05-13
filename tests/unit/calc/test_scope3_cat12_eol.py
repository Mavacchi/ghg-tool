"""Unit tests for scope3_cat12_eol (FR-17)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope3_cat12_eol
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _row(
    *, quantita: str = "1000", anno: int = 2024,
    categoria_s3: int = 12,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "sottocategoria": "EOL_Piastrelle",
        "quantita": quantita,
        "anno": anno,
        "categoria_s3": categoria_s3,
    }


def test_split_30_70(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat12_eol.calculate(
        [_row(quantita="1000")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert len(out) == 2
    # landfill 30%: 8.0 × 300 × 0.001 = 2.400
    landfill = next(r for r in out if "ECOINV_LANDFILL_INERT_V3_10" in r.factor_id)
    recycle = next(r for r in out if "ECOINV_CDW_RECYCLE_V3_10" in r.factor_id)
    assert landfill.tco2e == Decimal("2.400")
    # recycle 70%: 2.0 × 700 × 0.001 = 1.400
    assert recycle.tco2e == Decimal("1.400")


def test_both_have_cat12_sub_scope(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat12_eol.calculate(
        [_row()], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert all(r.sub_scope == "Cat12" for r in out)
    assert all(r.methodology == "mass-based" for r in out)


def test_non_cat12_skipped(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat12_eol.calculate(
        [_row(categoria_s3=9)], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out == []


def test_disclosure_calls_out_cut_off(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope3_cat12_eol.calculate(
        [_row()], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    recycle = next(r for r in out if "RECYCLE" in r.factor_id)
    assert "cut-off" in (recycle.disclosure_notes or "")


def test_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row()
    row["id"] = str(row["id"])
    out = scope3_cat12_eol.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert all(isinstance(r.raw_row_id, uuid.UUID) for r in out)


def test_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _row()
    row["id"] = None
    out = scope3_cat12_eol.calculate(
        [row], catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    assert all(r.raw_row_id is None for r in out)
