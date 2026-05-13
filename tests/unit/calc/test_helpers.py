"""Unit tests for the shared ``_helpers`` module under application/calc."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from ghg_tool.application.calc._helpers import (
    KG_TO_TONNE,
    make_emission,
    require_factor,
    sum_decimals,
    to_decimal,
    utc_now,
)
from ghg_tool.domain.exceptions.calc_errors import MissingFactorError
from ghg_tool.domain.ports.factor_catalog import FactorRecord
from tests.unit.calc.conftest import InMemoryFactorCatalog


def test_kg_to_tonne_value() -> None:
    assert Decimal("0.001") == KG_TO_TONNE


def test_utc_now_is_aware() -> None:
    ts = utc_now()
    assert ts.tzinfo is not None
    assert ts.utcoffset() == ts.utcoffset()  # any non-None offset is OK


def test_to_decimal_int() -> None:
    assert to_decimal(42) == Decimal(42)


def test_to_decimal_float_via_str() -> None:
    assert to_decimal(0.1) == Decimal("0.1")


def test_to_decimal_str() -> None:
    assert to_decimal("  3.14 ") == Decimal("3.14")


def test_to_decimal_already_decimal() -> None:
    assert to_decimal(Decimal("7")) == Decimal("7")


def test_to_decimal_invalid_raises() -> None:
    with pytest.raises(TypeError, match="Cannot coerce"):
        to_decimal(None)  # type: ignore[arg-type]


def test_sum_decimals_empty() -> None:
    assert sum_decimals([]) == Decimal("0")


def test_sum_decimals_values() -> None:
    assert sum_decimals([Decimal("1"), Decimal("2.5")]) == Decimal("3.5")


def test_require_factor_returns_record(catalog: InMemoryFactorCatalog) -> None:
    rec = require_factor(catalog, "STOICH_CACO3_IPCC_2006", gwp_set="AR6")
    assert rec.value == Decimal("0.4397")


def test_require_factor_missing_raises(catalog: InMemoryFactorCatalog) -> None:
    with pytest.raises(MissingFactorError):
        require_factor(catalog, "NOT_A_FACTOR", gwp_set="AR6")


def test_require_factor_none_value_raises() -> None:
    catalog = InMemoryFactorCatalog({
        ("BAD", "AR6"): FactorRecord(
            factor_id="BAD", version="v", value=None, unit="x",
            source="X", gwp_set="AR6",
        )
    })
    with pytest.raises(MissingFactorError, match="no pinned value"):
        require_factor(catalog, "BAD", gwp_set="AR6")


def test_make_emission_stamps_fields(
    catalog: InMemoryFactorCatalog, correlation_id: uuid.UUID,
) -> None:
    factor = require_factor(catalog, "STOICH_CACO3_IPCC_2006", gwp_set="AR6")
    rec = make_emission(
        correlation_id=correlation_id,
        raw_row_id=None,
        scope=1,
        sub_scope="process",
        codice_sito="IANO",
        anno=2024,
        tco2e=Decimal("100"),
        factor=factor,
        gwp_set="AR6",
        methodology="stoichiometric",
        regulatory_stream="CSRD_ESRS_E1",
        created_by="t",
    )
    assert rec.factor_id == "STOICH_CACO3_IPCC_2006"
    assert rec.factor_version == "2025"
    assert rec.factor_source == "IPCC"
    assert rec.calc_timestamp.tzinfo is not None
