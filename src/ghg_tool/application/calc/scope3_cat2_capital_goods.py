"""Scope 3 — Cat 2 Capital Goods (FR-10).

Spend-based EXIOBASE for Impiantistica (NACE C28) and Materiali di
consumo (NACE C27).  Factor unit: kg CO2e / EUR.
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

_FACTOR_MAP: dict[str, str] = {
    "impiantistica": "EXIO_MACHINERY_NACE_C28",
    "materiali di consumo": "EXIO_CONSUMABLES_NACE_C27",
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
    """Compute Scope 3 Cat 2 EmissionRecords (spend-based EXIOBASE).

    Args:
        raw_rows: Iterable of raw Scope 3 row dicts.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of ``EmissionRecord`` instances with ``sub_scope='Cat2'``.
    """
    records: list[EmissionRecord] = []
    for row in raw_rows:
        if int(row.get("categoria_s3", 0)) != 2:
            continue
        sub = str(row["sottocategoria"]).strip().lower()
        factor_id = _FACTOR_MAP.get(sub)
        if factor_id is None:
            continue
        factor = require_factor(factors, factor_id, gwp_set=gwp.code)
        spend = to_decimal(row["quantita"])  # spend EUR
        tco2e = (factor.value or Decimal("0")) * spend * KG_TO_TONNE
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=_uuid_or_none(row.get("id")),
                scope=3,
                sub_scope="Cat2",
                codice_sito=None,
                anno=int(row["anno"]),
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="spend-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 2 spend-based EXIOBASE: {row.get('sottocategoria', '')!s} "
                    f"({spend} EUR via {factor_id})."
                ),
            )
        )
    return records
