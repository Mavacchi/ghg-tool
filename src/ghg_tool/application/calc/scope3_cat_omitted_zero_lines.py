"""Scope 3 — omitted-with-rationale zero-lines for Cat 8/10/13/14/15 (FR-36, MG-07).

Each emits one zero-line ``EmissionRecord`` per reporting year with a
category-specific rationale text sourced from
methodology_validation.md §3.3.

Sub-scopes used:
  * ``Cat8_ZERO``  — Upstream leased assets
  * ``Cat10_ZERO`` — Processing of sold products
  * ``Cat13_ZERO`` — Downstream leased assets
  * ``Cat14_ZERO`` — Franchises
  * ``Cat15_ZERO`` — Financed emissions
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc._helpers import make_emission
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort, FactorRecord
from ghg_tool.domain.ports.gwp_table import GWPTablePort

# (sub_scope, rationale, synthetic factor_id) — ordered for deterministic output
_OMITTED_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "Cat8_ZERO",
        (
            "Cat 8 not applicable — all leased assets, where present, are consolidated within "
            "the operational-control boundary and accounted for in Scope 1 and Scope 2."
        ),
        "CAT8_ZERO_OMISSION",
    ),
    (
        "Cat10_ZERO",
        (
            "Cat 10 not applicable — finished products (gres porcellanato tiles) undergo no "
            "industrial processing between sale and end-use."
        ),
        "CAT10_ZERO_OMISSION",
    ),
    (
        "Cat13_ZERO",
        (
            "Cat 13 not applicable — the company is not a lessor of operational assets."
        ),
        "CAT13_ZERO_OMISSION",
    ),
    (
        "Cat14_ZERO",
        (
            "Cat 14 not applicable — the company operates no franchise network."
        ),
        "CAT14_ZERO_OMISSION",
    ),
    (
        "Cat15_ZERO",
        (
            "Cat 15 not applicable — the company is a non-financial undertaking and holds no "
            "investment portfolio in scope of GHG Protocol Cat 15 (OI-8 closed 2026-05-13)."
        ),
        "CAT15_ZERO_OMISSION",
    ),
)


def calculate(
    factors: FactorCatalogPort,  # noqa: ARG001 — uniform signature, factors unused for synth zeros
    gwp: GWPTablePort,
    *,
    anno: int,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Emit the 5 omitted-category zero-lines for one reporting year.

    Args:
        factors: Factor catalog port (unused; signature uniformity).
        gwp: GWP table — code stamped on emitted rows.
        anno: Reporting year.
        correlation_id: Shared run identifier.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.

    Returns:
        List of 5 ``EmissionRecord`` zero-rows.
    """
    return [
        make_emission(
            correlation_id=correlation_id,
            raw_row_id=None,
            scope=3,
            sub_scope=sub_scope,
            codice_sito=None,
            anno=anno,
            tco2e=Decimal("0"),
            factor=_synth_factor(factor_id, rationale, gwp.code),
            gwp_set=gwp.code,
            methodology="declared-zero",
            regulatory_stream=regulatory_stream,
            created_by=created_by,
            disclosure_notes=rationale,
        )
        for (sub_scope, rationale, factor_id) in _OMITTED_CATEGORIES
    ]


def _synth_factor(factor_id: str, rationale: str, gwp_set: str) -> FactorRecord:
    """Return a synthetic FactorRecord descriptor for a Cat-zero row.

    Args:
        factor_id: Synthetic factor identifier.
        rationale: Disclosure rationale text.
        gwp_set: GWP code to record.

    Returns:
        ``FactorRecord`` with value=0 and synthetic provenance metadata.
    """
    return FactorRecord(
        factor_id=factor_id,
        version="2026-05-13",
        value=Decimal("0"),
        unit="tCO2e",
        source="FR-36 / MG-07 declared-zero",
        gwp_set=gwp_set,
        applicability_note=rationale,
    )
