"""Sync SQLAlchemy adapter satisfying FactorCatalogPort.

Wires the calc orchestrator to the real factor catalog without needing an
async event loop. Uses psycopg (sync) via a SQLAlchemy sync Engine so the
port's sync method signatures are honoured exactly.

Draft factors (is_published=False) are never returned. The adapter
caches FactorRecord instances in a plain dict keyed by
(factor_id, gwp_set, vintage_year) for the lifetime of the instance.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import Engine, text

from ghg_tool.domain.exceptions.calc_errors import MissingFactorError
from ghg_tool.domain.ports.factor_catalog import FactorRecord

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SQL — pure parameterised; no f-string interpolation.
# ---------------------------------------------------------------------------

_SELECT_FACTOR = text(
    """
    SELECT
        id,
        factor_id,
        version,
        value,
        unit,
        source,
        gwp_set,
        biogenic_co2_kg_per_unit,
        vintage,
        applicability_note,
        is_tbc,
        is_licence_only
    FROM ref.factor_catalog
    WHERE tenant_id     = :tenant_id
      AND factor_id     = :factor_id
      AND gwp_set       = :gwp_set
      AND is_published  = TRUE
      AND valid_to      IS NULL
    ORDER BY valid_from DESC
    LIMIT 1
    """
)

_SELECT_FACTOR_VINTAGE = text(
    """
    SELECT
        id,
        factor_id,
        version,
        value,
        unit,
        source,
        gwp_set,
        biogenic_co2_kg_per_unit,
        vintage,
        applicability_note,
        is_tbc,
        is_licence_only
    FROM ref.factor_catalog
    WHERE tenant_id     = :tenant_id
      AND factor_id     = :factor_id
      AND gwp_set       = :gwp_set
      AND is_published  = TRUE
      AND vintage       = CAST(:vintage_year AS TEXT)
    ORDER BY valid_from DESC
    LIMIT 1
    """
)


def _row_to_factor_record(row: Any) -> FactorRecord:
    """Convert a DB row (mapping) into a domain FactorRecord.

    Args:
        row: Row returned by SQLAlchemy Core execute (RowMapping).

    Returns:
        Constructed FactorRecord with ``factor_db_id`` populated from the
        ``id`` column so the persistence layer can satisfy the FK constraint
        on ``calc.emissions_consolidated.factor_id``.
    """
    value = Decimal(str(row["value"])) if row["value"] is not None else None
    biogenic = (
        Decimal(str(row["biogenic_co2_kg_per_unit"]))
        if row["biogenic_co2_kg_per_unit"] is not None
        else None
    )
    db_id: uuid.UUID | None = uuid.UUID(str(row["id"])) if row["id"] is not None else None
    return FactorRecord(
        factor_id=row["factor_id"],
        version=row["version"],
        value=value,
        unit=row["unit"],
        source=row["source"],
        gwp_set=row["gwp_set"],
        biogenic_co2_kg_per_unit=biogenic,
        vintage=row["vintage"],
        applicability_note=row["applicability_note"],
        is_tbc=bool(row["is_tbc"]),
        is_licence_only=bool(row["is_licence_only"]),
        factor_db_id=db_id,
    )


class SqlFactorCatalogAdapter:
    """Sync FactorCatalogPort backed by a SQLAlchemy sync Engine (psycopg).

    Instance-level cache keyed by (factor_id, gwp_set, vintage_year) so
    repeated look-ups within a single calc run hit the dict rather than
    issuing duplicate SELECT statements.

    Implements FactorCatalogPort structurally (duck-typing Protocol).
    """

    def __init__(
        self,
        tenant_id: uuid.UUID,
        *,
        sync_engine: Engine,
    ) -> None:
        """Initialise the adapter.

        Args:
            tenant_id: The tenant UUID to scope all factor look-ups.
            sync_engine: A sync SQLAlchemy Engine (psycopg driver).
        """
        self._tenant_id = tenant_id
        self._engine = sync_engine
        self._cache: dict[tuple[str, str, int | None], FactorRecord] = {}

    def _fetch(
        self,
        factor_id: str,
        *,
        gwp_set: str,
        vintage_year: int | None,
    ) -> FactorRecord:
        """Execute the SELECT and return a FactorRecord or raise MissingFactorError.

        Args:
            factor_id: Catalog key.
            gwp_set: 'AR6' or 'AR5'.
            vintage_year: Optional vintage filter.

        Returns:
            FactorRecord from the DB.

        Raises:
            MissingFactorError: When no published row matches.
        """
        params: dict[str, Any] = {
            "tenant_id": str(self._tenant_id),
            "factor_id": factor_id,
            "gwp_set": gwp_set,
        }
        stmt = _SELECT_FACTOR_VINTAGE if vintage_year is not None else _SELECT_FACTOR
        if vintage_year is not None:
            params["vintage_year"] = vintage_year

        log = logger.bind(
            tenant_id=str(self._tenant_id),
            factor_id=factor_id,
            gwp_set=gwp_set,
            vintage_year=vintage_year,
        )

        with self._engine.connect() as conn:
            result = conn.execute(stmt, params)
            row = result.mappings().first()

        if row is None:
            log.warning("factor_not_found")
            raise MissingFactorError(
                f"No published factor for factor_id={factor_id!r} "
                f"gwp_set={gwp_set!r} vintage_year={vintage_year!r} "
                f"tenant_id={self._tenant_id}"
            )

        log.debug("factor_fetched", version=row["version"])
        return _row_to_factor_record(row)

    def get(
        self,
        factor_id: str,
        *,
        gwp_set: str,
        vintage_year: int | None = None,
    ) -> FactorRecord:
        """Return the active FactorRecord for the given factor_id and gwp_set.

        Results are cached for the lifetime of this adapter instance.

        Args:
            factor_id: Catalog key.
            gwp_set: 'AR6' or 'AR5'.
            vintage_year: Optional vintage filter; falls back to the
                valid_to IS NULL active row when None.

        Returns:
            The matching FactorRecord.

        Raises:
            MissingFactorError: When no active published row is found.
        """
        cache_key = (factor_id, gwp_set, vintage_year)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._fetch(
                factor_id, gwp_set=gwp_set, vintage_year=vintage_year
            )
        return self._cache[cache_key]

    def get_biogenic_share(
        self,
        factor_id: str,
        *,
        gwp_set: str,
    ) -> Decimal | None:
        """Return the biogenic CO2 share for an ADR-007 factor.

        Uses the same cache as get() (via vintage_year=None).

        Args:
            factor_id: Catalog key.
            gwp_set: 'AR6' or 'AR5'.

        Returns:
            Biogenic CO2 share as Decimal, or None.
        """
        try:
            record = self.get(factor_id, gwp_set=gwp_set)
        except MissingFactorError:
            return None
        return record.biogenic_co2_kg_per_unit
