"""Scope 3 — Cat 4 Upstream Transport (FR-12).

Distance-based: tkm × DEFRA mode-specific freight factor.  Modes: HGV
road, rail, sea.  Zero-tkm rows are retained as explicit 0.0 emissions
(FR-12 acceptance criterion).
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

# Sub-category text fragments → factor_id mode
_MODE_FACTOR_IDS: dict[str, str] = {
    "strada": "FREIGHT_HGV_DEFRA_2025",
    "hgv": "FREIGHT_HGV_DEFRA_2025",
    "camion": "FREIGHT_HGV_DEFRA_2025",
    "treno": "FREIGHT_RAIL_DEFRA_2025",
    "rail": "FREIGHT_RAIL_DEFRA_2025",
    "nave": "FREIGHT_SEA_DEFRA_2025",
    "sea": "FREIGHT_SEA_DEFRA_2025",
    "mare": "FREIGHT_SEA_DEFRA_2025",
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
    """Compute Scope 3 Cat 4 EmissionRecords for upstream transport.

    Args:
        raw_rows: Iterable of raw Scope 3 row dicts.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of ``EmissionRecord`` instances with ``sub_scope='Cat4'``.
    """
    records: list[EmissionRecord] = []
    for row in raw_rows:
        if int(row.get("categoria_s3", 0)) != 4:
            continue
        factor_id = _resolve_mode(str(row["sottocategoria"]))
        if factor_id is None:
            continue
        factor = require_factor(factors, factor_id, gwp_set=gwp.code)
        tkm = to_decimal(row["quantita"])
        tco2e = (factor.value or Decimal("0")) * tkm * KG_TO_TONNE  # 0.0 for tkm=0
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=_uuid_or_none(row.get("id")),
                scope=3,
                sub_scope="Cat4",
                codice_sito=None,
                anno=int(row["anno"]),
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="distance-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 4 distance-based: {row.get('sottocategoria', '')!s} "
                    f"({tkm} tkm via {factor.factor_id})."
                ),
            )
        )
    return records


def _resolve_mode(sottocategoria: str) -> str | None:
    """Resolve a Sottocategoria string to a freight factor_id.

    Args:
        sottocategoria: Free-text Cat 4 sub-category label.

    Returns:
        Factor catalog ID for the resolved mode, or ``None`` if no match.
    """
    lowered = sottocategoria.lower()
    for key, factor_id in _MODE_FACTOR_IDS.items():
        if key in lowered:
            return factor_id
    return None


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Coerce a value to UUID if possible; else None.

    Args:
        value: Source value.

    Returns:
        ``uuid.UUID`` or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
