"""Scope 3 — Cat 5 Waste Generated in Operations (FR-13).

Mass-based: tonne × DEFRA / ecoinvent waste factor.  Cut-off methodology
(no avoided-emissions credit for recycling).  Separate factors for:
  * Landfill pericolosi (hazardous)
  * Landfill non-pericolosi (non-hazardous)
  * Recycling pericolosi
  * Recycling non-pericolosi
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


def calculate(
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 3 Cat 5 EmissionRecords for waste disposal.

    Args:
        raw_rows: Iterable of raw Scope 3 row dicts.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of ``EmissionRecord`` instances with ``sub_scope='Cat5'``.
    """
    records: list[EmissionRecord] = []
    for row in raw_rows:
        if int(row.get("categoria_s3", 0)) != 5:
            continue
        factor_id = _resolve_waste_factor(str(row["sottocategoria"]))
        if factor_id is None:
            continue
        factor = require_factor(factors, factor_id, gwp_set=gwp.code)
        tonnes = to_decimal(row["quantita"])
        tco2e = (factor.value or Decimal("0")) * tonnes * KG_TO_TONNE
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=_uuid_or_none(row.get("id")),
                scope=3,
                sub_scope="Cat5",
                codice_sito=None,
                anno=int(row["anno"]),
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="mass-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 5 cut-off (no avoided-emissions credit): "
                    f"{row.get('sottocategoria', '')!s} ({tonnes} t via {factor.factor_id})."
                ),
            )
        )
    return records


def _resolve_waste_factor(sottocategoria: str) -> str | None:
    """Resolve a waste Sottocategoria to a factor_id.

    Decision logic (lower-cased input):
      * Hazardous flag = ``'pericol' in label and 'non pericol' not in label``
        — defends against the false positive where 'non pericolosi'
        contains the 'pericol' substring.
      * 'discarica' / 'landfill' → landfill family
      * 'ricicl' / 'recycl' → recycle family
      * Combined with hazardous flag for full classification.

    Args:
        sottocategoria: Sottocategoria label.

    Returns:
        Factor catalog ID, or ``None`` if no rule matches.
    """
    label = sottocategoria.lower()
    is_perilous = "pericol" in label and "non pericol" not in label
    is_landfill = "discarica" in label or "landfill" in label
    is_recycle = "ricicl" in label or "recycl" in label
    if is_landfill and is_perilous:
        return "WASTE_LANDFILL_PERIC_DEFRA_2025"
    if is_landfill:
        return "WASTE_LANDFILL_NONPERIC_DEFRA_2025"
    if is_recycle and is_perilous:
        return "WASTE_RECYCLE_PERIC_DEFRA_2025"
    if is_recycle:
        return "WASTE_RECYCLE_NONPERIC_DEFRA_2025"
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
