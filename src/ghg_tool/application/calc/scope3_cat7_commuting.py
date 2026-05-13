"""Scope 3 — Cat 7 Employee Commuting (FR-15).

Distance-based DEFRA average-car factor × Σ Commuting_Auto km.
FTE 506 (2024) / 484 (2025) annotated in disclosure_notes.
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

_FACTOR_ID = "COMMUTE_CAR_DEFRA_2025"

# FTE counts confirmed by user 2026-05-13 (HR official)
_FTE_PER_ANNO: dict[int, int] = {2024: 506, 2025: 484}

# Methodology baseline — derived from ISTAT 2024 commuting survey (Italy,
# all employees, weighted avg).  Used in disclosure_notes only; never feeds
# emission arithmetic.  Promoted to a module-level constant (REV-018) so
# the number is not embedded as a magic literal inside an f-string.
_KM_PER_FTE_YR_BASELINE: int = 8_800


def calculate(
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 3 Cat 7 EmissionRecords (employee commuting).

    Args:
        raw_rows: Iterable of raw Scope 3 row dicts.  Only rows whose
            ``sottocategoria`` contains 'commuting_auto' (case-insensitive)
            and ``categoria_s3 == 7`` are processed.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of ``EmissionRecord`` instances with ``sub_scope='Cat7'``.
    """
    factor = require_factor(factors, _FACTOR_ID, gwp_set=gwp.code)
    records: list[EmissionRecord] = []
    for row in raw_rows:
        if int(row.get("categoria_s3", 0)) != 7:
            continue
        if "commuting" not in str(row.get("sottocategoria", "")).lower():
            continue
        km = to_decimal(row["quantita"])
        tco2e = (factor.value or Decimal("0")) * km * KG_TO_TONNE
        anno = int(row["anno"])
        fte = _FTE_PER_ANNO.get(anno)
        records.append(
            make_emission(
                correlation_id=correlation_id,
                raw_row_id=_uuid_or_none(row.get("id")),
                scope=3,
                sub_scope="Cat7",
                codice_sito=None,
                anno=anno,
                tco2e=tco2e,
                factor=factor,
                gwp_set=gwp.code,
                methodology="distance-based",
                regulatory_stream=regulatory_stream,
                created_by=created_by,
                disclosure_notes=(
                    f"Cat 7 distance-based commuting: {km} km via {factor.factor_id}. "
                    f"FTE={fte if fte is not None else 'n/a'} (HR official 2026-05-13); "
                    f"km/FTE/yr estimate = {_KM_PER_FTE_YR_BASELINE:,} (methodology baseline)."
                ),
            )
        )
    return records


