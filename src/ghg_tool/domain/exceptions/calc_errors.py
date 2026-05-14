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
    ``ghg_tool.domain.entities.emission_record.ALLOWED_SUB_SCOPES``.
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


class InvalidGWPSetError(CalcError):
    """Raised when an EmissionRecord or IntensityMetric carries an unknown gwp_set.

    Per FR-19 / FR-34, the only allowed GWP set codes are ``AR6`` (CSRD default)
    and ``AR5`` (EU ETS dual-track).  ``AR4`` or any free-text value is rejected
    at the domain boundary.
    """


class InvalidMethodologyError(CalcError):
    """Raised when an EmissionRecord declares a methodology not in the allowed vocabulary.

    Allowed values live in
    ``ghg_tool.domain.entities.emission_record.ALLOWED_METHODOLOGIES``.
    Examples of allowed values: ``activity-based``, ``mass-based``,
    ``spend-based``, ``distance-based``, ``stoichiometric``,
    ``declared-zero``, ``location-based``, ``market-based``.
    """


class InvalidRegulatoryStreamError(CalcError):
    """Raised when an EmissionRecord declares a regulatory_stream not in the allowed set.

    Allowed values: ``CSRD_ESRS_E1`` (default) and ``EU_ETS_PHASE_IV`` (dual-track
    AR5 stream).  See FR-34 and architecture.md §8.
    """


class NaiveTimestampError(CalcError):
    """Raised when an EmissionRecord or IntensityMetric ``calc_timestamp`` is naive.

    All persisted timestamps must be timezone-aware (UTC) per the
    architecture.md §8 calc-immutability contract.  Naive datetimes are
    rejected at construction time.
    """


class InvalidIntensityDenominatorError(CalcError):
    """Raised when an IntensityMetric denominator is non-positive.

    Per FR-25 / CSRD ESRS E1-6 §45 the denominator (production tonnes,
    revenue M EUR, or FTE headcount) must be strictly positive; a zero or
    negative value indicates either missing data or a degenerate division
    that would produce an undefined intensity ratio.
    """
