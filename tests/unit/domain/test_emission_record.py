"""Unit tests for EmissionRecord domain entity.

Mirrors the architecture.md §9 schema; verifies frozen invariants,
validation rules, and sub_scope vocabulary per scope.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.exceptions.calc_errors import (
    InvalidSubScopeError,
    NegativeEmissionError,
)


def _kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "correlation_id": uuid.uuid4(),
        "raw_row_id": None,
        "scope": 1,
        "sub_scope": "combustion",
        "codice_sito": "IANO",
        "anno": 2024,
        "tco2e": Decimal("1.234567"),
        "factor_id": "FX",
        "factor_version": "v1",
        "factor_source": "DEFRA",
        "gwp_set": "AR6",
        "methodology": "activity-based",
        "regulatory_stream": "CSRD_ESRS_E1",
        "calc_timestamp": datetime.now(UTC),
        "created_by": "tester",
    }
    base.update(overrides)
    return base


def test_minimal_construction() -> None:
    rec = EmissionRecord(**_kwargs())
    assert rec.scope == 1
    assert rec.tco2e == Decimal("1.234567")
    assert isinstance(rec.id, uuid.UUID)


def test_frozen_blocks_mutation() -> None:
    rec = EmissionRecord(**_kwargs())
    with pytest.raises(AttributeError):
        rec.tco2e = Decimal("0")  # type: ignore[misc]


def test_negative_tco2e_rejected() -> None:
    with pytest.raises(NegativeEmissionError):
        EmissionRecord(**_kwargs(tco2e=Decimal("-0.001")))


def test_invalid_scope_rejected() -> None:
    with pytest.raises(ValueError, match="scope"):
        EmissionRecord(**_kwargs(scope=4))


def test_invalid_sub_scope_for_scope_rejected() -> None:
    with pytest.raises(InvalidSubScopeError):
        EmissionRecord(**_kwargs(scope=1, sub_scope="Cat1"))


def test_scope2_allows_lb_mb() -> None:
    for s in ("LB", "MB"):
        rec = EmissionRecord(**_kwargs(scope=2, sub_scope=s))
        assert rec.sub_scope == s


def test_scope3_cat_subscopes() -> None:
    for s in ("Cat1", "Cat2", "Cat3_WTT_FUEL", "Cat11_ZERO", "Cat15_ZERO"):
        rec = EmissionRecord(**_kwargs(scope=3, sub_scope=s))
        assert rec.sub_scope == s


def test_invalid_methodology_rejected() -> None:
    with pytest.raises(ValueError, match="methodology"):
        EmissionRecord(**_kwargs(methodology="bad_method"))


def test_invalid_regulatory_stream_rejected() -> None:
    with pytest.raises(ValueError, match="regulatory_stream"):
        EmissionRecord(**_kwargs(regulatory_stream="MARKET_DAILY"))


def test_invalid_gwp_set_rejected() -> None:
    with pytest.raises(ValueError, match="gwp_set"):
        EmissionRecord(**_kwargs(gwp_set="AR4"))


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EmissionRecord(**_kwargs(calc_timestamp=datetime(2024, 1, 1)))  # noqa: DTZ001


def test_negative_biogenic_rejected() -> None:
    with pytest.raises(ValueError, match="co2_biogenic_tonne"):
        EmissionRecord(**_kwargs(
            scope=3, sub_scope="Cat1",
            tco2e=Decimal("1"),
            co2_biogenic_tonne=Decimal("-0.001"),
        ))


def test_negative_fossil_rejected() -> None:
    with pytest.raises(ValueError, match="co2_fossil_tonne"):
        EmissionRecord(**_kwargs(
            scope=3, sub_scope="Cat1",
            tco2e=Decimal("1"),
            co2_fossil_tonne=Decimal("-0.001"),
        ))


def test_optional_fields_default_none() -> None:
    rec = EmissionRecord(**_kwargs())
    assert rec.co2_tonne is None
    assert rec.co2_biogenic_tonne is None
    assert rec.co2_fossil_tonne is None
    assert rec.disclosure_notes is None
    assert rec.uncertainty_band_lower is None
    assert rec.uncertainty_band_upper is None


def test_ar5_stream_eu_ets() -> None:
    rec = EmissionRecord(**_kwargs(
        gwp_set="AR5", regulatory_stream="EU_ETS_PHASE_IV",
    ))
    assert rec.gwp_set == "AR5"
    assert rec.regulatory_stream == "EU_ETS_PHASE_IV"


def test_uncertainty_bands_can_be_set() -> None:
    rec = EmissionRecord(**_kwargs(
        uncertainty_band_lower=Decimal("0.1"),
        uncertainty_band_upper=Decimal("0.3"),
    ))
    assert rec.uncertainty_band_lower == Decimal("0.1")
    assert rec.uncertainty_band_upper == Decimal("0.3")
