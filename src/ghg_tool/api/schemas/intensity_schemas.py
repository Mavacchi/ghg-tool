"""Pydantic v2 schemas for GET /api/v1/intensity (FR-25, FR-26).

IntensityRow mirrors the columns produced by the intensity service and
stored in calc.mv_intensity_metrics (or equivalent persistence layer).
IntensityResponse wraps a list of rows with request metadata.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntensityRow(BaseModel):
    """A single intensity-metric row for one (anno, scope_label, site) bucket.

    Maps one-to-one to the columns in ``calc.mv_intensity_metrics``.
    ``from_attributes=True`` allows construction directly from ORM model
    instances when the view is available; hand-mapping from
    ``IntensityMetric`` dataclasses works via normal keyword-arg construction.

    Attributes:
        anno: Reporting year.
        codice_sito: Site code; ``None`` when the row is a multi-site aggregate.
        scope_label: Emission scope discriminator including Scope2 variant.
        intensity_value: tCO2e per denominator unit.
        denominator_value: Raw denominator quantity.
        denominator_unit: Human-readable unit label (e.g. 'EUR', 'm2', 'FTE', 'kg').
        gwp_set: GWP characterisation set used in the numerator calc.
        factor_source: Primary factor source identifier.
        factor_version: Factor version string.
        methodology: Calculation methodology tag.
        hr_confirmation_date: HR-confirmed effective date for FTE denominators
            (REV-017 traceability); ``None`` for non-FTE denominators.
        confidence_interval_lower: Lower bound of 95% bootstrap CI; ``None`` if
            not computed.
        confidence_interval_upper: Upper bound of 95% bootstrap CI; ``None`` if
            not computed.
        correlation_id: Run identifier shared with the underlying emission rows.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    anno: int
    codice_sito: str | None = None
    scope_label: Literal["Scope1", "Scope2_LB", "Scope2_MB", "Scope3", "Total"]
    intensity_value: Decimal
    denominator_value: Decimal
    denominator_unit: str
    gwp_set: str
    factor_source: str
    factor_version: str
    methodology: str
    hr_confirmation_date: date | None = None
    confidence_interval_lower: Decimal | None = None
    confidence_interval_upper: Decimal | None = None
    correlation_id: str


class IntensityResponse(BaseModel):
    """Response envelope for ``GET /api/v1/intensity``.

    Attributes:
        rows: List of intensity-metric rows matching the query filters.
        denominator_type: The denominator type used in the query
            (``EUR_revenue``, ``m2_production``, ``FTE``, or ``kg_product``).
        gwp_set: GWP characterisation set used for the response rows.
        anno_from: Earliest reporting year included.
        anno_to: Latest reporting year included.
        correlation_id: Request-level correlation UUID (FR-22).
        as_of: UTC timestamp at which the query was executed.
        note: Optional informational note (e.g. when the MV is not yet
            available and a stub response is returned).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True, populate_by_name=True)

    rows: list[IntensityRow] = Field(default_factory=list)
    denominator_type: str
    gwp_set: str
    anno_from: int
    anno_to: int
    correlation_id: str
    as_of: datetime
    note: str | None = Field(default=None, alias="_note")
