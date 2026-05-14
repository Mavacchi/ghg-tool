"""Intensity service — KPI-09, KPI-10, KPI-11 (FR-25).

Computes the three CSRD ESRS E1-6 §45 intensity ratios from a list of
``EmissionRecord`` rows plus reference inputs (production tonnage,
revenue, FTE).  Both LB and MB Scope 2 variants are produced.

Pure-function: no DB I/O.  The orchestrator (or backend service) is
responsible for sourcing the reference inputs and persisting the
returned ``IntensityMetric`` rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.entities.intensity_metric import IntensityMetric
from ghg_tool.domain.exceptions.calc_errors import InvalidIntensityDenominatorError


@dataclass(frozen=True, slots=True)
class IntensityReferenceInputs:
    """Reference inputs needed to compute intensity ratios for one year.

    Attributes:
        anno: Reporting year.
        production_tonnes: Total tonnes of gres porcellanato produced.
        revenue_meur: Net revenue in M EUR.
        fte: Full-time-equivalent headcount (HR official).
        hr_confirmation_date: Effective date on which HR officially confirmed
            the FTE figure.  Used verbatim in ``disclosure_notes``.  Per
            REV-017 the date must be supplied explicitly by the caller — no
            in-code default — so the timestamp is not bound to the calc
            session's clock.  In production wiring this should be the
            ``effective_from`` value of the HR FTE entry in the factor
            catalog (or equivalent reference table).
    """

    anno: int
    production_tonnes: Decimal
    revenue_meur: Decimal
    fte: int
    hr_confirmation_date: date


def compute_intensities(
    emissions: Iterable[EmissionRecord],
    references: Iterable[IntensityReferenceInputs],
    *,
    correlation_id: uuid.UUID,
    gwp_set: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
    created_by: str = "intensity_service",
    calc_timestamp: datetime | None = None,
) -> list[IntensityMetric]:
    """Compute KPI-09 / KPI-10 / KPI-11 for every (anno, scope2_variant).

    For each ``IntensityReferenceInputs`` row, derives numerator totals
    from the supplied emissions and applies the denominator to obtain
    the intensity ratio.  Two scope2_variants — LB and MB — are computed
    per year.

    Args:
        emissions: Iterable of ``EmissionRecord``; only matching gwp_set
            and regulatory_stream rows are aggregated.
        references: Iterable of reference inputs (one per anno).
        correlation_id: Shared run identifier.
        gwp_set: 'AR6' or 'AR5'.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        created_by: User / service-account identifier.
        calc_timestamp: Override timestamp; defaults to ``datetime.now(UTC)``.

    Returns:
        List of ``IntensityMetric`` rows (3 KPIs × 2 variants × N years).
    """
    ts = calc_timestamp if calc_timestamp is not None else datetime.now(UTC)
    em_list = [e for e in emissions
               if e.gwp_set == gwp_set and e.regulatory_stream == regulatory_stream]

    out: list[IntensityMetric] = []
    for ref in references:
        for variant in ("LB", "MB"):
            numerator = _sum_total(em_list, ref.anno, scope2_variant=variant)
            out.extend(_build_kpis(
                numerator=numerator,
                ref=ref,
                variant=variant,
                correlation_id=correlation_id,
                gwp_set=gwp_set,
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                calc_timestamp=ts,
            ))
    return out


def _sum_total(
    emissions: list[EmissionRecord],
    anno: int,
    *,
    scope2_variant: str,
) -> Decimal:
    """Sum tCO2e for one year, including only the chosen Scope 2 variant.

    Scope 1 (all) + Scope 2 (selected variant) + Scope 3 (all sub_scopes).

    Args:
        emissions: List of pre-filtered ``EmissionRecord`` rows.
        anno: Year filter.
        scope2_variant: Either 'LB' or 'MB'.

    Returns:
        Σ tCO2e as ``Decimal``.
    """
    total = Decimal("0")
    for e in emissions:
        if e.anno != anno:
            continue
        if e.scope == 2 and e.sub_scope != scope2_variant:
            continue
        total += e.tco2e
    return total


def _build_kpis(  # noqa: PLR0913 — explicit kwargs make the call-site self-documenting
    *,
    numerator: Decimal,
    ref: IntensityReferenceInputs,
    variant: str,
    correlation_id: uuid.UUID,
    gwp_set: str,
    regulatory_stream: str,
    created_by: str,
    calc_timestamp: datetime,
) -> list[IntensityMetric]:
    """Build the three KPI rows for one (anno, variant) pair.

    Args:
        numerator: Σ tCO2e for the year × variant.
        ref: Reference inputs (denominators).
        variant: 'LB' or 'MB'.
        correlation_id: Run identifier.
        gwp_set: 'AR6' or 'AR5'.
        regulatory_stream: Stream tag.
        created_by: User identifier.
        calc_timestamp: Calc timestamp.

    Returns:
        List with three ``IntensityMetric`` rows (KPI-09, 10, 11).
    """
    # REV-017: HR confirmation date is sourced from the reference input,
    # not from a session-time literal.  Caller (orchestrator) must thread
    # the date through so the disclosure annotation remains stable across
    # re-runs and replays.
    notes = (
        f"FTE={ref.fte} (HR official {ref.hr_confirmation_date}); "
        f"scope2_variant={variant}."
    )
    fte_dec = Decimal(ref.fte)
    # Guard against degenerate denominators before division so a domain-typed
    # exception surfaces instead of decimal.DivisionByZero / ZeroDivisionError.
    if ref.production_tonnes <= Decimal("0"):
        raise InvalidIntensityDenominatorError(
            f"production_tonnes must be > 0; got {ref.production_tonnes} "
            f"(anno={ref.anno})"
        )
    if ref.revenue_meur <= Decimal("0"):
        raise InvalidIntensityDenominatorError(
            f"revenue_meur must be > 0; got {ref.revenue_meur} (anno={ref.anno})"
        )
    if fte_dec <= Decimal("0"):
        raise InvalidIntensityDenominatorError(
            f"fte must be > 0; got {ref.fte} (anno={ref.anno})"
        )
    return [
        IntensityMetric(
            correlation_id=correlation_id,
            kpi_code="KPI-09",
            anno=ref.anno,
            scope2_variant=variant,
            numerator_tco2e=numerator,
            denominator_value=ref.production_tonnes,
            denominator_unit="t",
            intensity_value=numerator / ref.production_tonnes,
            gwp_set=gwp_set,
            regulatory_stream=regulatory_stream,
            calc_timestamp=calc_timestamp,
            created_by=created_by,
            disclosure_notes=notes,
        ),
        IntensityMetric(
            correlation_id=correlation_id,
            kpi_code="KPI-10",
            anno=ref.anno,
            scope2_variant=variant,
            numerator_tco2e=numerator,
            denominator_value=ref.revenue_meur,
            denominator_unit="M EUR",
            intensity_value=numerator / ref.revenue_meur,
            gwp_set=gwp_set,
            regulatory_stream=regulatory_stream,
            calc_timestamp=calc_timestamp,
            created_by=created_by,
            disclosure_notes=notes,
        ),
        IntensityMetric(
            correlation_id=correlation_id,
            kpi_code="KPI-11",
            anno=ref.anno,
            scope2_variant=variant,
            numerator_tco2e=numerator,
            denominator_value=fte_dec,
            denominator_unit="FTE",
            intensity_value=numerator / fte_dec,
            gwp_set=gwp_set,
            regulatory_stream=regulatory_stream,
            calc_timestamp=calc_timestamp,
            created_by=created_by,
            disclosure_notes=notes,
        ),
    ]
