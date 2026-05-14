"""Scope 3 — Cat 11 zero-line (FR-18, MG-06).

Use of sold products is omitted as immaterial for ceramic tiles:
gres porcellanato is a passive product with no operational energy
consumption during the use phase (Cerame-Unie sector position;
methodology_validation §8).

One zero-line ``EmissionRecord`` per reporting year with the fixed
rationale text.  The orchestrator should call this once per ``anno``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from ghg_tool.application.calc._helpers import make_emission
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort, FactorRecord
from ghg_tool.domain.ports.gwp_table import GWPTablePort

_RATIONALE: str = (
    "Omitted — Immaterial: ceramic tiles are passive products with no "
    "operational energy consumption during use phase."
)
_SYNTH_FACTOR_ID = "CAT11_ZERO_OMISSION"


def calculate(
    factors: FactorCatalogPort,  # noqa: ARG001 — uniform signature
    gwp: GWPTablePort,
    *,
    anno: int,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Emit one Cat 11 zero-line for the reporting year.

    Args:
        factors: Factor catalog port (unused).
        gwp: GWP table — code stamped on emitted row.
        anno: Reporting year.
        correlation_id: Shared run identifier.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.

    Returns:
        Single-element list with the Cat 11 zero ``EmissionRecord``.
    """
    factor = FactorRecord(
        factor_id=_SYNTH_FACTOR_ID,
        version="2026-05-13",
        value=Decimal("0"),
        unit="tCO2e",
        source="FR-18 / MG-06 declared-zero",
        gwp_set=gwp.code,
        applicability_note=_RATIONALE,
    )
    return [
        make_emission(
            correlation_id=correlation_id,
            raw_row_id=None,
            scope=3,
            sub_scope="Cat11_ZERO",
            codice_sito=None,
            anno=anno,
            tco2e=Decimal("0"),
            factor=factor,
            gwp_set=gwp.code,
            methodology="declared-zero",
            regulatory_stream=regulatory_stream,
            created_by=created_by,
            disclosure_notes=_RATIONALE,
        )
    ]
