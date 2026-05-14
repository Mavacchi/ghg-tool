"""Unit tests for IntensityMetric domain entity."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ghg_tool.domain.entities.intensity_metric import IntensityMetric
from ghg_tool.domain.exceptions.calc_errors import (
    CalcError,
    InvalidGWPSetError,
    InvalidIntensityDenominatorError,
    NaiveTimestampError,
)


def _kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "correlation_id": uuid.uuid4(),
        "kpi_code": "KPI-09",
        "anno": 2024,
        "scope2_variant": "LB",
        "numerator_tco2e": Decimal("1000"),
        "denominator_value": Decimal("100"),
        "denominator_unit": "t",
        "intensity_value": Decimal("10"),
        "gwp_set": "AR6",
        "regulatory_stream": "CSRD_ESRS_E1",
        "calc_timestamp": datetime.now(UTC),
        "created_by": "tester",
    }
    base.update(overrides)
    return base


def test_minimal_construction() -> None:
    m = IntensityMetric(**_kwargs())
    assert m.kpi_code == "KPI-09"
    assert m.scope2_variant == "LB"
    assert isinstance(m.id, uuid.UUID)


def test_frozen_blocks_mutation() -> None:
    m = IntensityMetric(**_kwargs())
    with pytest.raises(AttributeError):
        m.intensity_value = Decimal("0")  # type: ignore[misc]


def test_invalid_kpi_code_rejected() -> None:
    with pytest.raises(ValueError, match="kpi_code"):
        IntensityMetric(**_kwargs(kpi_code="KPI-99"))


def test_invalid_scope2_variant_rejected() -> None:
    with pytest.raises(ValueError, match="scope2_variant"):
        IntensityMetric(**_kwargs(scope2_variant="HYBRID"))


def test_invalid_gwp_set_rejected() -> None:
    with pytest.raises(InvalidGWPSetError, match="gwp_set"):
        IntensityMetric(**_kwargs(gwp_set="AR4"))


def test_non_positive_denominator_rejected() -> None:
    with pytest.raises(InvalidIntensityDenominatorError, match="denominator_value"):
        IntensityMetric(**_kwargs(denominator_value=Decimal("0")))


def test_negative_denominator_rejected() -> None:
    """REV-020: negative denominator is also rejected via dedicated exception."""
    with pytest.raises(InvalidIntensityDenominatorError, match="denominator_value"):
        IntensityMetric(**_kwargs(denominator_value=Decimal("-1")))


def test_negative_numerator_rejected() -> None:
    with pytest.raises(ValueError, match="numerator_tco2e"):
        IntensityMetric(**_kwargs(numerator_tco2e=Decimal("-1")))


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(NaiveTimestampError, match="timezone-aware"):
        IntensityMetric(**_kwargs(calc_timestamp=datetime(2024, 1, 1)))  # noqa: DTZ001


# ---------------------------------------------------------------------------
# REV-020: new exception types subclass CalcError
# ---------------------------------------------------------------------------


def test_invalid_intensity_denominator_is_calc_error() -> None:
    assert issubclass(InvalidIntensityDenominatorError, CalcError)
