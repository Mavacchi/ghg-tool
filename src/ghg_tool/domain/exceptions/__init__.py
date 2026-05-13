"""Domain exceptions package — calc errors, mismatches, validation failures."""

from ghg_tool.domain.exceptions.calc_errors import (
    CalcError,
    FactorUnitMismatchError,
    GOValidationError,
    GWPSetMismatchError,
    InvalidSubScopeError,
    MissingFactorError,
    NegativeEmissionError,
)

__all__ = [
    "CalcError",
    "FactorUnitMismatchError",
    "GOValidationError",
    "GWPSetMismatchError",
    "InvalidSubScopeError",
    "MissingFactorError",
    "NegativeEmissionError",
]
