"""Scope 3 — Cat 3 Fuel and Energy related activities (FR-11, MG-05).

WTT + T&D loss emissions:
  * Fuel WTT per fuel = WTT factor × Σ Scope 1 fuel quantity per (fuel, year)
  * Electricity WTT     = WTT_ELEC factor × Σ kWh per year (LB basis)
  * T&D losses          = TND_ELEC_IT factor × Σ kWh per year

Critical FR-11 rule: fuel input is **Σ Scope 1**, NOT the CSV Cat 3
``Quantità`` column.  The CSV Quantità delta is logged by
``etl.cat3_reconciliation`` regardless of value.

The calc returns ``EmissionRecord`` rows tagged with sub_scopes
``Cat3_WTT_FUEL`` (per fuel/year), ``Cat3_WTT_ELEC`` (per year), and
``Cat3_TND`` (per year).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import Decimal

from ghg_tool.application.calc._helpers import (
    KG_TO_TONNE,
    make_emission,
    require_factor,
    to_decimal,
)
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort
from ghg_tool.domain.ports.gwp_table import GWPTablePort

# Per-fuel WTT factor IDs
_FUEL_WTT_FACTOR_IDS: dict[str, str] = {
    "GAS_NAT": "WTT_GAS_NAT_DEFRA_2025",
    "GASOLIO": "WTT_GASOLIO_DEFRA_2025",
    "BENZINA": "WTT_BENZINA_DEFRA_2025",
}
_ELEC_WTT_ID = "WTT_ELEC_DEFRA_2025"
_TND_ELEC_IT_ID = "TND_ELEC_IT_DEFRA_2025"

# Pre-aggregated input shapes:
SigmaScope1 = Mapping[tuple[str, int], Decimal]  # (combustibile, anno) -> Σ quantita
SigmaScope2 = Mapping[int, Decimal]              # anno -> Σ kWh


def calculate(  # noqa: PLR0913 — explicit named DI; complexity managed by sub-helpers
    *,
    sigma_scope1: SigmaScope1,
    sigma_scope2_kwh: SigmaScope2,
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 3 Cat 3 WTT + T&D EmissionRecords from Scope 1/2 aggregates.

    Args:
        sigma_scope1: Mapping ``(combustibile, anno) -> Σ Scope 1 quantita``.
            Source-of-truth fuel input for WTT (FR-11).
        sigma_scope2_kwh: Mapping ``anno -> Σ kWh consumed (LB basis)``.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of ``EmissionRecord`` rows for fuel WTT, electricity WTT, and T&D.
    """
    records: list[EmissionRecord] = []
    records.extend(_fuel_wtt_records(
        sigma_scope1, factors, gwp, correlation_id, created_by, regulatory_stream
    ))
    records.extend(_electricity_wtt_records(
        sigma_scope2_kwh, factors, gwp, correlation_id, created_by, regulatory_stream
    ))
    records.extend(_tnd_records(
        sigma_scope2_kwh, factors, gwp, correlation_id, created_by, regulatory_stream
    ))
    return records


def _fuel_wtt_records(  # noqa: PLR0913 — internal slice
    sigma_scope1: SigmaScope1,
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str,
) -> list[EmissionRecord]:
    """Compute WTT emissions per (combustibile, anno) using Σ Scope 1 input.

    Args:
        sigma_scope1: Mapping (combustibile, anno) -> Σ quantita.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of WTT fuel records, sorted by key for determinism.
    """
    records: list[EmissionRecord] = []
    for (combustibile, anno) in sorted(sigma_scope1.keys()):
        sigma = to_decimal(sigma_scope1[(combustibile, anno)])
        factor_id = _FUEL_WTT_FACTOR_IDS.get(combustibile)
        if factor_id is None:
            continue
        factor = require_factor(factors, factor_id, gwp_set=gwp.code)
        tco2e = (factor.value or Decimal("0")) * sigma * KG_TO_TONNE
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=None,
                scope=3,
                sub_scope="Cat3_WTT_FUEL",
                codice_sito=None,
                anno=anno,
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="activity-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 3 WTT {combustibile} (FR-11 Σ Scope 1 source-of-truth): "
                    f"Σ={sigma} via {factor.factor_id}."
                ),
            )
        )
    return records


def _electricity_wtt_records(  # noqa: PLR0913 — internal slice
    sigma_scope2_kwh: SigmaScope2,
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str,
) -> list[EmissionRecord]:
    """Compute WTT electricity emissions per year.

    Args:
        sigma_scope2_kwh: Mapping anno -> Σ kWh.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of WTT electricity records.
    """
    factor = require_factor(factors, _ELEC_WTT_ID, gwp_set=gwp.code)
    records: list[EmissionRecord] = []
    for anno in sorted(sigma_scope2_kwh.keys()):
        sigma = to_decimal(sigma_scope2_kwh[anno])
        tco2e = (factor.value or Decimal("0")) * sigma * KG_TO_TONNE
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=None,
                scope=3,
                sub_scope="Cat3_WTT_ELEC",
                codice_sito=None,
                anno=anno,
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="activity-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 3 WTT electricity (LB basis): Σ={sigma} kWh via {factor.factor_id}."
                ),
            )
        )
    return records


def _tnd_records(  # noqa: PLR0913 — internal slice
    sigma_scope2_kwh: SigmaScope2,
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str,
) -> list[EmissionRecord]:
    """Compute T&D losses per year.

    Args:
        sigma_scope2_kwh: Mapping anno -> Σ kWh.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of T&D records.
    """
    factor = require_factor(factors, _TND_ELEC_IT_ID, gwp_set=gwp.code)
    records: list[EmissionRecord] = []
    for anno in sorted(sigma_scope2_kwh.keys()):
        sigma = to_decimal(sigma_scope2_kwh[anno])
        tco2e = (factor.value or Decimal("0")) * sigma * KG_TO_TONNE
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=None,
                scope=3,
                sub_scope="Cat3_TND",
                codice_sito=None,
                anno=anno,
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="activity-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 3 T&D electricity (Italy loss rate): "
                    f"Σ={sigma} kWh via {factor.factor_id}."
                ),
            )
        )
    return records
