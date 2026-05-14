"""Scope 1 — Fugitive HFC zero-line (FR-35, MG-18, OI-10 closed).

Emits one zero-line ``EmissionRecord`` per site per reporting year with
``sub_scope='fugitive'`` and the standard OI-10 rationale.

No raw input — fully synthesised.  ``raw_row_id`` is ``None`` to mark
the row as ETL-synthesised (NFR-18 traceability is satisfied by the
``disclosure_notes`` rationale and the FR-35 rule_id audit trail).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from decimal import Decimal

from ghg_tool.application.calc._helpers import make_emission
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort, FactorRecord
from ghg_tool.domain.ports.gwp_table import GWPTablePort

_RATIONALE: str = (
    "FR-35 / MG-18 / OI-10 closure: Closed-loop refrigeration systems; "
    "refrigerant top-ups across all 7 sites declared negligible by user 2026-05-13. "
    "Zero-line is a disclosure of completeness, not an absence of accounting. "
    "Supersedable via FR-21 correction workflow if future inventory data emerges."
)

_SYNTH_FACTOR_ID = "FUGITIVE_ZERO_OI_10"


def calculate(
    sites: Iterable[str],
    factors: FactorCatalogPort,  # noqa: ARG001 — kept for uniform signature
    gwp: GWPTablePort,
    *,
    anno: int,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Emit one fugitive zero-line per site for the given reporting year.

    Args:
        sites: Iterable of 7 site codes (IANO, VIANO, VIANO_GARGOLA,
            CASALGRANDE, FIORANO, SASSUOLO, FRASSINORO).
        factors: Factor catalog port (unused; kept for uniform calc signature).
        gwp: GWP table; the ``code`` is stamped on emitted rows.
        anno: Reporting year (e.g. 2024 or 2025).
        correlation_id: Shared run identifier.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.

    Returns:
        List of ``EmissionRecord`` zero-rows — one per site.
    """
    synth_factor = _synth_factor_record(gwp.code)
    return [
        make_emission(
            correlation_id=correlation_id,
            raw_row_id=None,
            scope=1,
            sub_scope="fugitive",
            codice_sito=codice_sito,
            anno=anno,
            tco2e=Decimal("0"),
            factor=synth_factor,
            gwp_set=gwp.code,
            methodology="declared-zero",
            regulatory_stream=regulatory_stream,
            created_by=created_by,
            co2_tonne=None,
            disclosure_notes=_RATIONALE,
        )
        for codice_sito in sites
    ]


def _synth_factor_record(gwp_set: str) -> FactorRecord:
    """Return the synthetic factor descriptor used to stamp provenance fields.

    Args:
        gwp_set: GWP code to record.

    Returns:
        A ``FactorRecord`` with value=0 and synthetic provenance metadata.
    """
    return FactorRecord(
        factor_id=_SYNTH_FACTOR_ID,
        version="2026-05-13",
        value=Decimal("0"),
        unit="tCO2e",
        source="OI-10 user confirmation",
        gwp_set=gwp_set,
        applicability_note=_RATIONALE,
    )
