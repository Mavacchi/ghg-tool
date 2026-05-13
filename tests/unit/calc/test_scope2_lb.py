"""Unit tests for scope2_lb.calculate (FR-07)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc import scope2_lb
from tests.unit.calc.conftest import InMemoryFactorCatalog


def _s2_row(
    *, quantita: str = "1000000", codice_sito: str = "IANO",
    voce_s2: str = "EE_Acquistata_Grid", anno: int = 2024,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "quantita": quantita,
        "codice_sito": codice_sito,
        "anno": anno,
        "voce_s2": voce_s2,
    }


def test_lb_applies_to_all_kwh(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    rows = [_s2_row(quantita="1000000")]
    out = scope2_lb.calculate(
        rows, catalog, ar6_gwp, correlation_id=correlation_id, created_by="t",
    )
    # 1,000,000 kWh × 0.27 kg / kWh × 0.001 = 270 tCO2e
    assert out[0].tco2e == Decimal("270.000")
    assert out[0].sub_scope == "LB"


def test_lb_methodology_label(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope2_lb.calculate(
        [_s2_row()], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].methodology == "location-based"


def test_lb_zero_kwh(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope2_lb.calculate(
        [_s2_row(quantita="0")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].tco2e == Decimal("0.000")


def test_lb_string_id_coerced(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _s2_row()
    row["id"] = str(row["id"])
    out = scope2_lb.calculate(
        [row], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert isinstance(out[0].raw_row_id, uuid.UUID)


def test_lb_none_id(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    row = _s2_row()
    row["id"] = None
    out = scope2_lb.calculate(
        [row], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert out[0].raw_row_id is None


def test_lb_disclosure_contains_voce_s2(
    catalog: InMemoryFactorCatalog, ar6_gwp, correlation_id: uuid.UUID,
) -> None:
    out = scope2_lb.calculate(
        [_s2_row(voce_s2="EE_Acquistata_GO")], catalog, ar6_gwp,
        correlation_id=correlation_id, created_by="t",
    )
    assert "EE_Acquistata_GO" in (out[0].disclosure_notes or "")
