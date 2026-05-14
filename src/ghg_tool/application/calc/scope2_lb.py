"""Scope 2 — Location-Based emissions (FR-07).

Applies the ISPRA Italian grid LB factor to total kWh per (site, year).
LB and MB are always kept as separate rows — never aggregated (FR-07
acceptance criterion).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from ghg_tool.application.calc._helpers import (
    KG_TO_TONNE,
    _uuid_or_none,
    make_emission,
    require_factor,
    to_decimal,
)
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort
from ghg_tool.domain.ports.gwp_table import GWPTablePort

_LB_FACTOR_ID = "LB_IT_GRID_ISPRA_2024"


def calculate(
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 2 LB EmissionRecords from raw Scope 2 kWh rows.

    For each raw Scope 2 row, applies the ISPRA Italian grid factor
    regardless of ``voce_s2`` (GO and Grid volumes both contribute to LB).

    Args:
        raw_rows: Iterable of raw Scope 2 row dicts (must carry id,
            codice_sito, anno, quantita, unita, voce_s2).
        factors: Factor catalog port.
        gwp: GWP100 lookup port; the ISPRA factor is already CO2e so GWP
            is applied as 1.0 (electricity factor is composite CO2e).
        correlation_id: Shared run identifier.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.

    Returns:
        List of ``EmissionRecord`` instances with ``sub_scope='LB'``.
    """
    factor = require_factor(factors, _LB_FACTOR_ID, gwp_set=gwp.code)
    records: list[EmissionRecord] = []
    for row in raw_rows:
        quantita_kwh = to_decimal(row["quantita"])
        # Factor unit is kg CO2 / kWh; multiply then convert kg → tonne.
        tco2e = (factor.value or Decimal("0")) * quantita_kwh * KG_TO_TONNE
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=_uuid_or_none(row.get("id")),
                scope=2,
                sub_scope="LB",
                codice_sito=str(row["codice_sito"]),
                anno=int(row["anno"]),
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="location-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                # ISPRA grid factor is total CO2e; record as co2_tonne for transparency
                co2_tonne=tco2e,
                co2_fossil_tonne=tco2e,
                disclosure_notes=(
                    f"Scope 2 LB: ISPRA factor applied to {quantita_kwh} kWh "
                    f"(voce_s2={row.get('voce_s2', 'unknown')!s})."
                ),
            )
        )
    return records
