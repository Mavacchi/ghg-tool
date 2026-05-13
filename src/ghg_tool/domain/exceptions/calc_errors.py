"""Calculation domain exceptions.

These are raised by the 16 calc modules under
``ghg_tool.application.calc`` and by the calc orchestrator service.
No framework imports — pure Python.
"""

from __future__ import annotations


class CalcError(Exception):
    """Base exception for all calculation-layer errors."""


class MissingFactorError(CalcError):
    """Raised when a calc module cannot find a required factor in the catalog.

    Per FR-04 / MG-01, every calculation row must carry ``factor_source``,
    ``factor_version`` and ``factor_id``.  A missing factor blocks the run.
    """


class GWPSetMismatchError(CalcError):
    """Raised when EmissionRecords with different gwp_set codes are combined.

    FR-19 / MG-10 forbid mixed AR6 and AR5 outputs in a single
    ``correlation_id``.  The orchestrator re-runs the calc with a uniform
    GWP table to produce the EU ETS dual-track AR5 output (FR-34 / MG-12).
    """


class InvalidSubScopeError(CalcError):
    """Raised when an EmissionRecord declares a sub_scope not allowed for its scope.

    Allowed sub_scope values per scope are enumerated in
    ``ghg_tool.domain.entities.emission_record._ALLOWED_SUB_SCOPES``.
    """


class NegativeEmissionError(CalcError):
    """Raised when a calc module attempts to construct an EmissionRecord with tco2e < 0.

    Defence-in-depth alongside the EmissionRecord ``__post_init__`` assertion.
    """


class GOValidationError(CalcError):
    """Raised when MB Scope 2 calc tries to apply MB=0 with no validated GO evidence.

    Per MG-03 / MG-14, an MB=0 factor can only apply where all 8 GO Quality
    Criteria are passed (per-certificate evidence in ref.go_certificate_evidence).
    """


class FactorUnitMismatchError(CalcError):
    """Raised when the unit declared on a factor does not match the raw row unit.

    Example: applying a kg-CO2e-per-kWh factor to a Sm3 fuel volume.
    """
