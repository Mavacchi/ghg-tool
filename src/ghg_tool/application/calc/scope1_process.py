"""Scope 1 — Process emissions (FR-06, MG-08, MG-09).

IANO only: Processo_Decarb stoichiometric CaCO3 → CaO + CO2.
Factor: ``STOICH_CACO3_IPCC_2006`` = 0.4397 tCO2/t CaCO3.

CO2 only — no CH4 / N2O components — so ``tco2e == co2_tonne``.
GWP=1 (CO2) is applied implicitly via the GWP table, but the value is a
stoichiometric chemistry constant (invariant under AR5/AR6 changes).

LOI ±10–20% uncertainty band per methodology_validation §6.4 is encoded
in ``disclosure_notes`` (MG-09).  The numeric band is **not** populated
in ``uncertainty_band_*`` since the band is methodology-level (not
bootstrap-derived).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from ghg_tool.application.calc._helpers import (
    make_emission,
    require_factor,
    to_decimal,
)
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort
from ghg_tool.domain.ports.gwp_table import GWPTablePort

_FACTOR_ID = "STOICH_CACO3_IPCC_2006"
_PROCESS_CATEGORY_TAG = "Processo_Decarb"
_LOI_UNCERTAINTY_NOTE: str = (
    "Stoichiometric factor 0.4397 tCO2/t CaCO3 (IPCC 2006 V3 Ch.2 §2.5.1.3 Table 2.1). "
    "CaCO3 mass estimated via LOI 3.5% method; uncertainty band "
    "±10–20% relative (methodology_validation §6.4 / MG-09). "
    "Tier-2 XRF / Tier-3 titration upgrade in Year-1 plan."
)


def calculate(
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 1 process emissions for IANO Processo_Decarb rows.

    Args:
        raw_rows: Iterable of raw Scope 1 row dicts; only rows where
            ``categoria_s1`` equals ``'Processo_Decarb'`` are processed.
        factors: Factor catalog port.
        gwp: GWP100 lookup port (CO2 GWP=1 invariant under AR5/AR6).
        correlation_id: Shared run identifier.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.

    Returns:
        List of ``EmissionRecord`` instances — one per Processo_Decarb row.
    """
    records: list[EmissionRecord] = []
    factor = require_factor(factors, _FACTOR_ID, gwp_set=gwp.code)
    # Defence-in-depth: invariance assertion — value must be 0.4397
    if factor.value != Decimal("0.4397"):
        raise ValueError(
            f"Stoichiometric factor value mismatch: expected 0.4397, "
            f"got {factor.value!r} for {factor.factor_id}"
        )

    for row in raw_rows:
        if str(row.get("categoria_s1", "")) != _PROCESS_CATEGORY_TAG:
            continue
        quantita_t = to_decimal(row["quantita"])  # t CaCO3
        co2_tonne = (factor.value) * quantita_t  # 0.4397 × tonnes CaCO3
        tco2e = co2_tonne * gwp.get("CO2")  # ×1; explicit for traceability

        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=_uuid_or_none(row.get("id")),
                scope=1,
                sub_scope="process",
                codice_sito=str(row["codice_sito"]),
                anno=int(row["anno"]),
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="stoichiometric",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                co2_tonne=co2_tonne,
                co2_fossil_tonne=co2_tonne,  # process CO2 from carbonate is fossil-classified
                ch4_tco2e=None,
                n2o_tco2e=None,
                disclosure_notes=_LOI_UNCERTAINTY_NOTE,
            )
        )
    return records


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
