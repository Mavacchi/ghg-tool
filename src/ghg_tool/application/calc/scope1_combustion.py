"""Scope 1 — Combustion emissions (FR-05, MG-04).

Calculates CO2 + CH4 + N2O contributions for stationary and mobile
combustion of GAS_NAT, GASOLIO and BENZINA, using DEFRA factors and
applying the GWPTable for CH4 / N2O conversion to CO2e.

Output: one ``EmissionRecord`` per (raw_row × component) where the
component is CO2 / CH4 / N2O folded into a single record (component
splits live in the ``co2_tonne`` / ``ch4_tco2e`` / ``n2o_tco2e`` columns).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from ghg_tool.application.calc._helpers import (
    KG_TO_TONNE,
    make_emission,
    require_factor,
    to_decimal,
)
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort
from ghg_tool.domain.ports.gwp_table import GWPTablePort

# DEFRA fuel-component factor IDs per fuel code.
# Each factor is kg of substance per native unit (Sm3 for GAS_NAT, litre for liquid fuels).
_FUEL_FACTOR_IDS: Mapping[str, dict[str, str]] = {
    "GAS_NAT": {
        "CO2": "COMB_GAS_NAT_CO2_DEFRA_2025",
        "CH4": "COMB_GAS_NAT_CH4_DEFRA_2025",
        "N2O": "COMB_GAS_NAT_N2O_DEFRA_2025",
    },
    "GASOLIO": {
        "CO2": "COMB_GASOLIO_CO2_DEFRA_2025",
        "CH4": "COMB_GASOLIO_CH4_DEFRA_2025",
        "N2O": "COMB_GASOLIO_N2O_DEFRA_2025",
    },
    "BENZINA": {
        "CO2": "COMB_BENZINA_CO2_DEFRA_2025",
        "CH4": "COMB_BENZINA_CH4_DEFRA_2025",
        "N2O": "COMB_BENZINA_N2O_DEFRA_2025",
    },
}


def calculate(
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 1 combustion EmissionRecords from raw Scope 1 rows.

    For each raw row whose ``combustibile`` is one of {GAS_NAT, GASOLIO,
    BENZINA}, looks up the three DEFRA component factors (CO2 / CH4 / N2O),
    multiplies by the row ``quantita`` and converts CH4/N2O kg→tCO2e via
    the GWP table.  CO2 contribution is set on both ``co2_tonne`` and
    ``co2_fossil_tonne`` (combustion CO2 is fossil-origin for these fuels).

    Args:
        raw_rows: Iterable of dict-like rows from ``raw.scope1_ingestions``
            (must carry keys: id, codice_sito, anno, combustibile, quantita).
        factors: Factor catalog port.
        gwp: GWP100 lookup port (AR6 default; AR5 for FR-34 dual-track).
        correlation_id: Shared run identifier.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' (default) or 'EU_ETS_PHASE_IV'.

    Returns:
        List of ``EmissionRecord`` instances (one per processed raw row).
    """
    records: list[EmissionRecord] = []
    for row in raw_rows:
        combustibile = str(row["combustibile"])
        if combustibile not in _FUEL_FACTOR_IDS:
            continue  # non-combustion fuels (e.g. process row) handled elsewhere
        # Skip explicit zero rows? No — we still emit explicit zero EmissionRecord
        # to keep raw_row_id traceability per NFR-18.
        records.append(
            _build_record(row, combustibile, factors, gwp, correlation_id, created_by,
                          regulatory_stream)
        )
    return records


def _build_record(  # noqa: PLR0913 — internal builder; arity tracks calculate's params
    row: Mapping[str, Any],
    combustibile: str,
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str,
) -> EmissionRecord:
    """Build a single combustion EmissionRecord for one raw row.

    Args:
        row: Raw Scope 1 row dict.
        combustibile: Fuel code (GAS_NAT / GASOLIO / BENZINA).
        factors: Factor catalog port.
        gwp: GWP100 lookup port.
        correlation_id: Shared run identifier.
        created_by: User identifier.
        regulatory_stream: Regulatory stream tag.

    Returns:
        A new ``EmissionRecord`` covering all three components for the row.
    """
    quantita = to_decimal(row["quantita"])
    factor_ids = _FUEL_FACTOR_IDS[combustibile]

    co2_factor = require_factor(factors, factor_ids["CO2"], gwp_set=gwp.code)
    ch4_factor = require_factor(factors, factor_ids["CH4"], gwp_set=gwp.code)
    n2o_factor = require_factor(factors, factor_ids["N2O"], gwp_set=gwp.code)

    # All factors are kg substance per native unit; substance kg = factor.value × quantita
    co2_kg = (co2_factor.value or Decimal("0")) * quantita
    ch4_kg = (ch4_factor.value or Decimal("0")) * quantita
    n2o_kg = (n2o_factor.value or Decimal("0")) * quantita

    co2_tonne = co2_kg * KG_TO_TONNE
    ch4_tco2e = ch4_kg * KG_TO_TONNE * gwp.get("CH4")
    n2o_tco2e = n2o_kg * KG_TO_TONNE * gwp.get("N2O")
    tco2e = co2_tonne + ch4_tco2e + n2o_tco2e

    return make_emission(
        correlation_id=correlation_id,
        raw_row_id=_uuid_or_none(row.get("id")),
        scope=1,
        sub_scope="combustion",
        codice_sito=str(row["codice_sito"]),
        anno=int(row["anno"]),
        tco2e=tco2e,
        factor=co2_factor,  # CO2 factor is the canonical anchor; CH4/N2O recorded in disclosure
        gwp_set=gwp.code,
        methodology="activity-based",
        regulatory_stream=regulatory_stream,
        created_by=created_by,
        co2_tonne=co2_tonne,
        co2_fossil_tonne=co2_tonne,
        ch4_tco2e=ch4_tco2e,
        n2o_tco2e=n2o_tco2e,
        disclosure_notes=(
            f"Combustion {combustibile}: CO2 factor={co2_factor.factor_id}, "
            f"CH4 factor={ch4_factor.factor_id}, N2O factor={n2o_factor.factor_id}."
        ),
    )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Coerce a value to UUID if possible; else None.

    Args:
        value: Source value (UUID, str, or None).

    Returns:
        ``uuid.UUID`` instance or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
