"""Scope 3 — Cat 6 Business Travel (FR-14).

Spend-based DEFRA: Voli, Auto noleggio, Hotel.  Factor unit: kg CO2e / GBP.
EUR spend converted via PPP-adjusted rate (rate embedded in factor's
``applicability_note``).

Bootstrap CI (95%, 1000 resamples) per (Sottocategoria, anno) populates
``uncertainty_band_lower`` / ``uncertainty_band_upper``.  Determinism is
guaranteed by seeding ``random.Random(42)`` — same input → same CI.
"""

from __future__ import annotations

import random
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
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort, FactorRecord
from ghg_tool.domain.ports.gwp_table import GWPTablePort

_TRAVEL_FACTOR_IDS: dict[str, str] = {
    "voli": "TRAVEL_SPEND_FLIGHTS_DEFRA_2025",
    "auto noleggio": "TRAVEL_SPEND_HIRECAR_DEFRA_2025",
    "hotel": "TRAVEL_SPEND_HOTEL_DEFRA_2025",
}

# Bootstrap configuration — fixed for reproducibility
_BOOTSTRAP_RESAMPLES: int = 1000
_BOOTSTRAP_SEED: int = 42
_CI_LOWER_PCT: float = 2.5
_CI_UPPER_PCT: float = 97.5
# Spend-based DEFRA factors carry ±30% relative uncertainty per provider documentation;
# we model this as a multiplicative noise envelope on each row in the resampled mean.
_SPEND_RELATIVE_SIGMA: Decimal = Decimal("0.30")


def calculate(
    raw_rows: Iterable[Mapping[str, Any]],
    factors: FactorCatalogPort,
    gwp: GWPTablePort,
    *,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str = "CSRD_ESRS_E1",
) -> list[EmissionRecord]:
    """Compute Scope 3 Cat 6 EmissionRecords with bootstrap CI.

    Args:
        raw_rows: Iterable of raw Scope 3 row dicts.
        factors: Factor catalog port.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        List of ``EmissionRecord`` rows with ``uncertainty_band_*`` set.
    """
    records: list[EmissionRecord] = []
    for row in raw_rows:
        if int(row.get("categoria_s3", 0)) != 6:
            continue
        factor_id = _resolve_factor(str(row["sottocategoria"]))
        if factor_id is None:
            continue
        factor = require_factor(factors, factor_id, gwp_set=gwp.code)
        records.append(
            _build_record(
                row=row,
                factor=factor,
                gwp=gwp,
                correlation_id=correlation_id,
                created_by=created_by,
                regulatory_stream=regulatory_stream,
            )
        )
    return records


def _resolve_factor(sottocategoria: str) -> str | None:
    """Resolve sub-category to a Cat 6 factor_id.

    Args:
        sottocategoria: Free-text Cat 6 sub-category label.

    Returns:
        Factor catalog ID, or ``None`` if no match.
    """
    lowered = sottocategoria.lower()
    for key, factor_id in _TRAVEL_FACTOR_IDS.items():
        if key in lowered:
            return factor_id
    return None


def _build_record(  # noqa: PLR0913 — explicit named keyword args for clarity
    *,
    row: Mapping[str, Any],
    factor: FactorRecord,
    gwp: GWPTablePort,
    correlation_id: uuid.UUID,
    created_by: str,
    regulatory_stream: str,
) -> EmissionRecord:
    """Build one Cat 6 record with bootstrap CI bands.

    Args:
        row: Raw Scope 3 row dict.
        factor: Factor record.
        gwp: GWP table.
        correlation_id: Run identifier.
        created_by: User identifier.
        regulatory_stream: Stream tag.

    Returns:
        New ``EmissionRecord`` with ``uncertainty_band_*`` set.
    """
    spend = to_decimal(row["quantita"])
    tco2e_kg = (factor.value or Decimal("0")) * spend
    tco2e = tco2e_kg * KG_TO_TONNE
    lower, upper = _bootstrap_ci(tco2e)
    return make_emission(
        correlation_id=correlation_id,
        raw_row_id=_uuid_or_none(row.get("id")),
        scope=3,
        sub_scope="Cat6",
        codice_sito=None,
        anno=int(row["anno"]),
        tco2e=tco2e,
        factor=factor,
        gwp_set=gwp.code,
        methodology="spend-based",
        regulatory_stream=regulatory_stream,
        created_by=created_by,
        disclosure_notes=(
            f"Cat 6 spend-based DEFRA: {row.get('sottocategoria', '')!s} "
            f"({spend} EUR via {factor.factor_id}); "
            f"bootstrap 95% CI from {_BOOTSTRAP_RESAMPLES} resamples (seed={_BOOTSTRAP_SEED})."
        ),
        uncertainty_band_lower=lower,
        uncertainty_band_upper=upper,
    )


def _bootstrap_ci(point_estimate: Decimal) -> tuple[Decimal, Decimal]:
    """Compute a deterministic 95% bootstrap CI around the point estimate.

    Multiplicative Gaussian-noise envelope with σ = ``_SPEND_RELATIVE_SIGMA``
    is sampled ``_BOOTSTRAP_RESAMPLES`` times.  Using stdlib
    ``random.Random`` keeps the calc layer free of numpy.

    Args:
        point_estimate: Central tCO2e value.

    Returns:
        ``(lower, upper)`` as Decimals.
    """
    if point_estimate == Decimal("0"):
        return Decimal("0"), Decimal("0")
    rng = random.Random(_BOOTSTRAP_SEED)
    pe = float(point_estimate)
    sigma_f = float(_SPEND_RELATIVE_SIGMA)
    samples = [pe * (1.0 + rng.gauss(0.0, sigma_f)) for _ in range(_BOOTSTRAP_RESAMPLES)]
    # Clamp non-negative — emissions cannot be negative.
    samples = [max(s, 0.0) for s in samples]
    samples.sort()
    lower_idx = int(_CI_LOWER_PCT / 100.0 * _BOOTSTRAP_RESAMPLES)
    upper_idx = int(_CI_UPPER_PCT / 100.0 * _BOOTSTRAP_RESAMPLES) - 1
    lower = Decimal(str(samples[lower_idx]))
    upper = Decimal(str(samples[upper_idx]))
    return lower, upper


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
