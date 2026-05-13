"""Domain entity: IntensityMetric — KPI-09, KPI-10, KPI-11.

Captures CSRD ESRS E1-6 §45 intensity ratios per FR-25:
  * KPI-09 — tCO2e per tonne produced
  * KPI-10 — tCO2e per M€ revenue
  * KPI-11 — tCO2e per FTE (headcount)

Each metric is computed against both LB and MB Scope 2 variants — that
choice is encoded in the ``scope2_variant`` discriminator (LB or MB).

Frozen, slots-based dataclass; framework-free.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from ghg_tool.domain.exceptions.calc_errors import (
    InvalidGWPSetError,
    InvalidIntensityDenominatorError,
    NaiveTimestampError,
)

_ALLOWED_KPI_CODES: frozenset[str] = frozenset({"KPI-09", "KPI-10", "KPI-11"})
_ALLOWED_SCOPE2_VARIANTS: frozenset[str] = frozenset({"LB", "MB"})
_ALLOWED_GWP_SETS: frozenset[str] = frozenset({"AR6", "AR5"})

Scope2Variant = Literal["LB", "MB"]
KPICode = Literal["KPI-09", "KPI-10", "KPI-11"]


@dataclass(frozen=True, slots=True)
class IntensityMetric:
    """Immutable intensity-metric row produced by ``intensity_service``.

    Attributes:
        id: UUID of the row (default uuid4).
        correlation_id: Run identifier shared with the underlying emission rows.
        kpi_code: One of {'KPI-09', 'KPI-10', 'KPI-11'}.
        anno: Reporting year.
        scope2_variant: Either 'LB' or 'MB' — disambiguates which Scope 2
            total feeds the numerator.
        numerator_tco2e: Total tCO2e in numerator (Scope 1 + Scope 2 + Scope 3).
        denominator_value: Production tonnage / revenue M€ / FTE count.
        denominator_unit: Free text label ('t', 'M EUR', 'FTE').
        intensity_value: ``numerator_tco2e / denominator_value``.
        gwp_set: 'AR6' or 'AR5'.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        calc_timestamp: UTC datetime at calc run.
        created_by: User / service-account identifier.
        disclosure_notes: Free-text annotation (e.g. FTE 506→484 source).
    """

    correlation_id: uuid.UUID
    kpi_code: str
    anno: int
    scope2_variant: str
    numerator_tco2e: Decimal
    denominator_value: Decimal
    denominator_unit: str
    intensity_value: Decimal
    gwp_set: str
    regulatory_stream: str
    calc_timestamp: datetime
    created_by: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    disclosure_notes: str | None = None

    def __post_init__(self) -> None:
        """Validate invariants.

        Raises:
            ValueError: When kpi_code or scope2_variant are out of vocab,
                or numerator_tco2e is negative.  These remain ValueError
                since they are enum-range / sign checks rather than
                domain-meaningful conditions on their own.
            InvalidGWPSetError: When gwp_set is not in ``{'AR6', 'AR5'}``.
            InvalidIntensityDenominatorError: When denominator_value is
                non-positive — a CSRD-level concern that deserves its own
                exception type per REV-020.
            NaiveTimestampError: When calc_timestamp lacks tzinfo.
        """
        if self.kpi_code not in _ALLOWED_KPI_CODES:
            raise ValueError(
                f"kpi_code={self.kpi_code!r} not in {sorted(_ALLOWED_KPI_CODES)}"
            )
        if self.scope2_variant not in _ALLOWED_SCOPE2_VARIANTS:
            raise ValueError(
                f"scope2_variant={self.scope2_variant!r} "
                f"not in {sorted(_ALLOWED_SCOPE2_VARIANTS)}"
            )
        if self.gwp_set not in _ALLOWED_GWP_SETS:
            raise InvalidGWPSetError(
                f"gwp_set={self.gwp_set!r} not in {sorted(_ALLOWED_GWP_SETS)}"
            )
        if self.denominator_value <= Decimal("0"):
            raise InvalidIntensityDenominatorError(
                f"denominator_value must be > 0; got {self.denominator_value} "
                f"(kpi={self.kpi_code}, anno={self.anno})"
            )
        if self.numerator_tco2e < Decimal("0"):
            raise ValueError(
                f"numerator_tco2e must be >= 0; got {self.numerator_tco2e}"
            )
        if self.calc_timestamp.tzinfo is None:
            raise NaiveTimestampError(
                "calc_timestamp must be timezone-aware (UTC); naive datetime rejected"
            )
