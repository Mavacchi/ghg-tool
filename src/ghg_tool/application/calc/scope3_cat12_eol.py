"""Scope 3 — Cat 12 End-of-Life Treatment of Sold Products (FR-17).

Mass-based × ecoinvent v3.10.  30% landfill / 70% recycling split per
proxy sectoral data (cut-off methodology — no avoided-emissions credit
for recycling).
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

_LANDFILL_FACTOR_ID = "ECOINV_LANDFILL_INERT_V3_10"
_RECYCLE_FACTOR_ID = "ECOINV_CDW_RECYCLE_V3_10"
_LANDFILL_FRACTION: Decimal = Decimal("0.30")
_RECYCLE_FRACTION: Decimal = Decimal("0.70")


def calculate(
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 3 Cat 12 EmissionRecords (end-of-life, 30/70 split).

    Emits two records per raw Cat 12 row: one for the landfill fraction,
    one for the recycling fraction.

    Args:
        raw_rows: Iterable of raw Scope 3 row dicts.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of ``EmissionRecord`` instances with ``sub_scope='Cat12'``.
    """
    landfill_factor = require_factor(factors, _LANDFILL_FACTOR_ID, gwp_set=gwp.code)
    recycle_factor = require_factor(factors, _RECYCLE_FACTOR_ID, gwp_set=gwp.code)

    records: list[EmissionRecord] = []
    for row in raw_rows:
        if int(row.get("categoria_s3", 0)) != 12:
            continue
        mass_t = to_decimal(row["quantita"])
        landfill_mass = mass_t * _LANDFILL_FRACTION
        recycle_mass = mass_t * _RECYCLE_FRACTION

        landfill_tco2e = (landfill_factor.value or Decimal("0")) * landfill_mass * KG_TO_TONNE
        recycle_tco2e = (recycle_factor.value or Decimal("0")) * recycle_mass * KG_TO_TONNE

        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=_uuid_or_none(row.get("id")),
                scope=3,
                sub_scope="Cat12",
                codice_sito=None,
                anno=int(row["anno"]),
                tco2e=landfill_tco2e,
                factor=landfill_factor,
                gwp_set=gwp.code,
                methodology="mass-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 12 landfill (30%) cut-off: "
                    f"{landfill_mass} t via {landfill_factor.factor_id}."
                ),
            )
        )
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=_uuid_or_none(row.get("id")),
                scope=3,
                sub_scope="Cat12",
                codice_sito=None,
                anno=int(row["anno"]),
                tco2e=recycle_tco2e,
                factor=recycle_factor,
                gwp_set=gwp.code,
                methodology="mass-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 12 recycling (70%) cut-off (no avoided-emissions credit): "
                    f"{recycle_mass} t via {recycle_factor.factor_id}."
                ),
            )
        )
    return records


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
