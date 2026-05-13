"""Tests for domain ports and calc exceptions."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ghg_tool.domain.exceptions.calc_errors import (
    CalcError,
    FactorUnitMismatchError,
    GOValidationError,
    GWPSetMismatchError,
    InvalidGWPSetError,
    InvalidIntensityDenominatorError,
    InvalidMethodologyError,
    InvalidRegulatoryStreamError,
    InvalidSubScopeError,
    MissingFactorError,
    NaiveTimestampError,
    NegativeEmissionError,
)
from ghg_tool.domain.ports.factor_catalog import FactorRecord
from ghg_tool.domain.ports.gwp_table import GWPSetTable
from ghg_tool.domain.value_objects.gwp_set import AR5, AR6


def test_factor_record_construction() -> None:
    r = FactorRecord(
        factor_id="ABC",
        version="2025",
        value=Decimal("0.5"),
        unit="kg CO2e / kg",
        source="DEFRA",
        gwp_set="AR6",
    )
    assert r.factor_id == "ABC"
    assert r.value == Decimal("0.5")


def test_factor_record_is_frozen() -> None:
    r = FactorRecord(
        factor_id="ABC", version="v", value=Decimal("1"),
        unit="x", source="DEFRA", gwp_set="AR6",
    )
    with pytest.raises(AttributeError):
        r.value = Decimal("2")  # type: ignore[misc]


def test_gwp_set_table_code_ar6() -> None:
    t = GWPSetTable(AR6)
    assert t.code == "AR6"


def test_gwp_set_table_code_ar5() -> None:
    t = GWPSetTable(AR5)
    assert t.code == "AR5"


def test_gwp_set_table_get_co2() -> None:
    assert GWPSetTable(AR6).get("CO2") == Decimal("1")


def test_gwp_set_table_get_ch4_ar6() -> None:
    assert GWPSetTable(AR6).get("CH4") == Decimal("27.9")


def test_gwp_set_table_get_n2o_ar5() -> None:
    assert GWPSetTable(AR5).get("N2O") == Decimal("265")


def test_gwp_set_table_get_hfc_dash_normalised() -> None:
    assert GWPSetTable(AR6).get("hfc_134a") == Decimal("1530")


def test_gwp_set_table_get_unknown_raises() -> None:
    with pytest.raises(KeyError, match="Unknown substance"):
        GWPSetTable(AR6).get("UNOBTAINIUM")


def test_calc_error_is_base() -> None:
    assert issubclass(MissingFactorError, CalcError)
    assert issubclass(GWPSetMismatchError, CalcError)
    assert issubclass(InvalidSubScopeError, CalcError)
    assert issubclass(NegativeEmissionError, CalcError)
    assert issubclass(GOValidationError, CalcError)
    assert issubclass(FactorUnitMismatchError, CalcError)
    # REV-019 / REV-020 — new exception types added pre-wave-3
    assert issubclass(InvalidGWPSetError, CalcError)
    assert issubclass(InvalidMethodologyError, CalcError)
    assert issubclass(InvalidRegulatoryStreamError, CalcError)
    assert issubclass(NaiveTimestampError, CalcError)
    assert issubclass(InvalidIntensityDenominatorError, CalcError)


def test_missing_factor_carries_message() -> None:
    err = MissingFactorError("missing X")
    assert "missing X" in str(err)
