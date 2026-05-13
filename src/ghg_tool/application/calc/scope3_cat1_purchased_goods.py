"""Scope 3 — Cat 1 Purchased Goods (FR-09, ADR-007).

Mass-based ecoinvent v3.10 for materials (argille, feldspati, sabbie
silicee, fritte, smalti, pigmenti, additivi, packaging) and spend-based
EXIOBASE for services.

ADR-007: cardboard (``ECOINV_CARDBOARD_V3_10``) and pallet
(``ECOINV_PALLET_V3_10``) must populate ``co2_biogenic_tonne`` AND
``co2_fossil_tonne`` columns separately.  ``tco2e`` carries only the
fossil + non-CO2 GWP-weighted total — biogenic CO2 is memo-only.
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

# Mapping of Sottocategoria text -> ecoinvent / EXIOBASE factor_id
# (lower-case keys for case-insensitive match)
_MATERIAL_FACTOR_MAP: dict[str, str] = {
    "argille": "ECOINV_CLAY_V3_10",
    "feldspati": "ECOINV_FELDSPAR_V3_10",
    "sabbie silicee": "ECOINV_SILICA_V3_10",
    "fritte": "ECOINV_FRIT_V3_10",
    "smalti": "ECOINV_FRIT_V3_10",
    "pigmenti": "ECOINV_PIGMENT_V3_10",
    "additivi": "ECOINV_ADDITIVES_V3_10",
    "imballaggi cartone": "ECOINV_CARDBOARD_V3_10",
    "pallet legno": "ECOINV_PALLET_V3_10",
    "film plastico": "ECOINV_LDPE_V3_10",
    "reggette pp": "ECOINV_PP_V3_10",
}

_SPEND_FACTOR_MAP: dict[str, str] = {
    "servizi vari": "EXIO_SERVICES_NACE_M",
}

# ADR-007 — factors with biogenic CO2 companion column
_BIOGENIC_FACTOR_IDS: frozenset[str] = frozenset({
    "ECOINV_CARDBOARD_V3_10",
    "ECOINV_PALLET_V3_10",
})


def calculate(
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 3 Cat 1 EmissionRecords for purchased goods + services.

    For each raw Scope 3 row where ``categoria_s3 == 1``:
      * Mass-based: looks up the ecoinvent factor by Sottocategoria, applies
        ``factor.value × quantita`` (already CO2e), converts kg → tonne, and
        for cardboard/pallet additionally populates biogenic columns.
      * Spend-based: looks up the EXIOBASE factor by Sottocategoria, applies
        the same conversion (factor is kg CO2e / EUR).

    Args:
        raw_rows: Iterable of raw Scope 3 row dicts.
        factors: Factor catalog port.
        gwp: GWP table (CSRD AR6 default; AR5 for EU ETS dual-track).
        correlation_id: Shared run identifier.
        created_by: User / service-account identifier.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.

    Returns:
        List of ``EmissionRecord`` instances with ``sub_scope='Cat1'``.
    """
    records: list[EmissionRecord] = []
    for row in raw_rows:
        if int(row.get("categoria_s3", 0)) != 1:
            continue
        sub = str(row["sottocategoria"]).strip().lower()
        factor_id = _MATERIAL_FACTOR_MAP.get(sub) or _SPEND_FACTOR_MAP.get(sub)
        if factor_id is None:
            continue  # unknown sub-category — skipped (orchestrator-level audit)
        records.append(
            _build_record(
                row=row,
                factor_id=factor_id,
                factors=factors,
                gwp=gwp,
                correlation_id=correlation_id,
                created_by=created_by,
                regulatory_stream=regulatory_stream,
                methodology="mass-based" if factor_id.startswith("ECOINV_") else "spend-based",
            )
        )
    return records


def _build_record(  # noqa: PLR0913 — internal builder dispatch
    *,
    row: Mapping[str, Any],
    factor_id: str,
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str,
    methodology: str,
) -> EmissionRecord:
    """Build one Cat 1 record, with ADR-007 biogenic split when applicable.

    Args:
        row: Raw Scope 3 row dict.
        factor_id: Resolved factor catalog ID.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.
        methodology: 'mass-based' or 'spend-based'.

    Returns:
        New ``EmissionRecord``.
    """
    factor = require_factor(factors, factor_id, gwp_set=gwp.code)
    quantita = to_decimal(row["quantita"])
    # factor.value already CO2e per unit; apply directly.
    tco2e_total_kg = (factor.value or Decimal("0")) * quantita
    tco2e_total = tco2e_total_kg * KG_TO_TONNE

    co2_biogenic_tonne: Decimal | None = None
    co2_fossil_tonne: Decimal | None = None

    if factor_id in _BIOGENIC_FACTOR_IDS:
        bio_share = factors.get_biogenic_share(factor_id, gwp_set=gwp.code)
        if bio_share is not None:
            biogenic_kg = bio_share * quantita
            co2_biogenic_tonne = biogenic_kg * KG_TO_TONNE
            # tco2e remains the fossil + non-CO2 GWP-weighted total; biogenic is memo-only
            co2_fossil_tonne = tco2e_total

    return make_emission(
        correlation_id=correlation_id,
        raw_row_id=_uuid_or_none(row.get("id")),
        scope=3,
        sub_scope="Cat1",
        codice_sito=None,  # corporate Cat 1 row; no per-site allocation
        anno=int(row["anno"]),
        tco2e=tco2e_total,
        factor=factor,
        gwp_set=gwp.code,
        methodology=methodology,
        regulatory_stream=regulatory_stream,
        created_by=created_by,
        co2_tonne=None,
        co2_biogenic_tonne=co2_biogenic_tonne,
        co2_fossil_tonne=co2_fossil_tonne,
        disclosure_notes=(
            f"Cat 1 {methodology}: {row.get('sottocategoria', '')!s} via {factor_id}."
            + (" Biogenic CO2 memo populated (ADR-007)." if co2_biogenic_tonne is not None else "")
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
