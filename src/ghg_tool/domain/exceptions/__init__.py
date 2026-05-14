"""Domain exceptions package — calc errors, mismatches, validation failures."""

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

__all__ = [
    "CalcError",
    "FactorUnitMismatchError",
    "GOValidationError",
    "GWPSetMismatchError",
    "InvalidGWPSetError",
    "InvalidIntensityDenominatorError",
    "InvalidMethodologyError",
    "InvalidRegulatoryStreamError",
    "InvalidSubScopeError",
    "MissingFactorError",
    "NaiveTimestampError",
    "NegativeEmissionError",
]
