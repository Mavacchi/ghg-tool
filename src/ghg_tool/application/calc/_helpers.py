"""Shared helpers for the 16 calc modules.

Private (leading underscore) module — not part of the public re-export
surface in ``application.calc.__init__``.  Calc modules import directly
from here.

All helpers are pure functions on stdlib types (``Decimal``,
``datetime``, dataclasses).  No pandas / numpy / database calls.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.exceptions.calc_errors import MissingFactorError
from ghg_tool.domain.ports.factor_catalog import FactorCatalogPort, FactorRecord

# ---------------------------------------------------------------------------
# Conversion factors
# ---------------------------------------------------------------------------

KG_TO_TONNE: Decimal = Decimal("0.001")
"""Multiplier converting kg → tonne."""


def utc_now() -> datetime:
    """Return current UTC datetime — single source of truth for calc timestamps.

    Returns:
        Current UTC ``datetime`` instance (timezone-aware).
    """
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Factor look-up wrappers
# ---------------------------------------------------------------------------

def require_factor(
    catalog: FactorCatalogPort,
    factor_id: str,
    *,
    gwp_set: str,
    vintage_year: int | None = None,
) -> FactorRecord:
    """Look up a factor; raise ``MissingFactorError`` if absent or value is None.

    Args:
        catalog: Factor catalog port.
        factor_id: Catalog key.
        gwp_set: 'AR6' or 'AR5'.
        vintage_year: Optional vintage filter.

    Returns:
        The looked-up ``FactorRecord`` with a non-None ``value``.

    Raises:
        MissingFactorError: If the catalog returns no record OR the record
            carries ``value is None`` (TBC / licence-only without runtime pin).
    """
    record = catalog.get(factor_id, gwp_set=gwp_set, vintage_year=vintage_year)
    if record.value is None:
        raise MissingFactorError(
            f"Factor {factor_id!r} (gwp_set={gwp_set!r}) has no pinned value. "
            "Pin via seed_loader or supply runtime value before calc."
        )
    return record


# ---------------------------------------------------------------------------
# EmissionRecord builders
# ---------------------------------------------------------------------------

def make_emission(  # noqa: PLR0913 — wrapper around dataclass with many optional fields
    *,
    correlation_id: uuid.UUID,
    raw_row_id: uuid.UUID | None,
    scope: int,
    sub_scope: str,
    codice_sito: str | None,
    anno: int,
    tco2e: Decimal,
    factor: FactorRecord,
    gwp_set: str,
    methodology: str,
    regulatory_stream: str,
    created_by: str,
    calc_timestamp: datetime | None = None,
    co2_tonne: Decimal | None = None,
    co2_biogenic_tonne: Decimal | None = None,
    co2_fossil_tonne: Decimal | None = None,
    ch4_tco2e: Decimal | None = None,
    n2o_tco2e: Decimal | None = None,
    disclosure_notes: str | None = None,
    uncertainty_band_lower: Decimal | None = None,
    uncertainty_band_upper: Decimal | None = None,
) -> EmissionRecord:
    """Construct an ``EmissionRecord`` with consistent provenance fields.

    Centralises the ``factor_id`` / ``factor_version`` / ``factor_source``
    field-stamping so every calc module produces records with the same
    provenance shape.

    Args:
        correlation_id: Run identifier shared by all rows in this calc run.
        raw_row_id: FK back to ``raw_*_ingestions``; ``None`` for synthesised
            zero-lines (FR-18 / FR-35 / FR-36).
        scope: 1, 2, or 3.
        sub_scope: Allowed sub_scope for the given scope.
        codice_sito: 7-site code or ``None`` for corporate-level rows.
        anno: Reporting year.
        tco2e: Total tonnes CO2-equivalent.
        factor: Factor catalog record (provides factor_id / version / source).
        gwp_set: 'AR6' or 'AR5'.
        methodology: One of the allowed methodology codes.
        regulatory_stream: 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        created_by: User / service-account identifier.
        calc_timestamp: Override timestamp; defaults to ``utc_now()``.
        co2_tonne: Optional direct CO2 mass (combustion + process).
        co2_biogenic_tonne: ADR-007 biogenic CO2 memo line.
        co2_fossil_tonne: ADR-007 fossil CO2 component.
        ch4_tco2e: Optional CH4 contribution in CO2e.
        n2o_tco2e: Optional N2O contribution in CO2e.
        disclosure_notes: Free-text disclosure annotation.
        uncertainty_band_lower: Optional bootstrap CI lower bound.
        uncertainty_band_upper: Optional bootstrap CI upper bound.

    Returns:
        A new immutable ``EmissionRecord``.
    """
    return EmissionRecord(
        correlation_id=correlation_id,
        raw_row_id=raw_row_id,
        scope=scope,
        sub_scope=sub_scope,
        codice_sito=codice_sito,
        anno=anno,
        tco2e=tco2e,
        factor_id=factor.factor_id,
        factor_version=factor.version,
        factor_source=factor.source,
        gwp_set=gwp_set,
        methodology=methodology,
        regulatory_stream=regulatory_stream,
        calc_timestamp=calc_timestamp if calc_timestamp is not None else utc_now(),
        created_by=created_by,
        co2_tonne=co2_tonne,
        co2_biogenic_tonne=co2_biogenic_tonne,
        co2_fossil_tonne=co2_fossil_tonne,
        ch4_tco2e=ch4_tco2e,
        n2o_tco2e=n2o_tco2e,
        factor_id_uuid=factor.factor_db_id,
        disclosure_notes=disclosure_notes,
        uncertainty_band_lower=uncertainty_band_lower,
        uncertainty_band_upper=uncertainty_band_upper,
    )


# ---------------------------------------------------------------------------
# Decimal coercion
# ---------------------------------------------------------------------------

def to_decimal(value: Any) -> Decimal:
    """Coerce a numeric / string value to ``Decimal`` without losing precision.

    Float inputs go through ``str()`` first so binary-fraction noise (e.g.
    ``0.1`` not being exactly representable) is avoided.

    Args:
        value: Numeric value (``int``, ``float``, ``str``, ``Decimal``).

    Returns:
        ``Decimal`` representation.

    Raises:
        TypeError: If ``value`` cannot be converted (e.g. None or list).
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value.strip())
    raise TypeError(
        f"Cannot coerce {type(value).__name__} to Decimal (value={value!r})"
    )


# ---------------------------------------------------------------------------
# Iterable summation
# ---------------------------------------------------------------------------

def sum_decimals(values: Iterable[Decimal]) -> Decimal:
    """Sum an iterable of Decimals returning ``Decimal('0')`` on empty input.

    Args:
        values: Iterable of ``Decimal`` summands.

    Returns:
        Sum as ``Decimal``.
    """
    total = Decimal("0")
    for v in values:
        total += v
    return total


# ---------------------------------------------------------------------------
# UUID coercion
# ---------------------------------------------------------------------------

def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Coerce a raw-row id value to ``uuid.UUID`` or return ``None``.

    Centralised here (REV-001) so the 11 calc modules no longer carry
    11 verbatim copies of the same helper.  Calc modules import this
    function rather than redefining it locally.

    Args:
        value: Source value (``uuid.UUID``, ``str``, or ``None``).

    Returns:
        ``uuid.UUID`` instance, or ``None`` when ``value`` is ``None``.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
