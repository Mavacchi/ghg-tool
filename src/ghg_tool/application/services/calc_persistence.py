"""End-to-end calc pipeline: load raw rows, run orchestrator, persist results.

This service bridges the sync world (SQLAlchemy sync Engine for raw reads
and factor catalog) and the async world (async session for appending to
calc.emissions_consolidated and ops.calc_runs).

Calling convention:
    run_calc_and_persist(...) is a plain sync function intended to be called
    from a CLI script or a background task runner. It internally uses
    asyncio.run() for the async persistence step.

Persistence guarantees:
    - calc.emissions_consolidated rows are INSERT-only (append-only contract).
    - ops.calc_runs is always written even when zero emission records are
      produced (so failed/empty runs are auditable).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ghg_tool.application.services.calc_orchestrator import (
    CalcOrchestrator,
    CalcRunInputs,
)
from ghg_tool.domain.entities.emission_record import EmissionRecord
from ghg_tool.domain.ports.gwp_table import GWPSetTable
from ghg_tool.domain.value_objects.gwp_set import AR6
from ghg_tool.infrastructure.db.session import set_session_gucs
from ghg_tool.infrastructure.factors.sql_adapter import SqlFactorCatalogAdapter

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalcPersistResult:
    """Summary of a completed calc-and-persist run.

    Attributes:
        emissions_written: Total rows inserted into calc.emissions_consolidated.
        scope1_count: Rows with scope=1.
        scope2_count: Rows with scope=2.
        scope3_count: Rows with scope=3.
        duration_ms: Wall-clock milliseconds for the full run.
        correlation_id: The UUID that ties this run to DB rows.
    """

    emissions_written: int
    scope1_count: int
    scope2_count: int
    scope3_count: int
    duration_ms: int
    correlation_id: uuid.UUID


# ---------------------------------------------------------------------------
# Raw row loading (sync)
# ---------------------------------------------------------------------------

_SELECT_SCOPE1 = text(
    """
    SELECT
        id, tenant_id, anno, codice_sito, categoria_s1,
        combustibile, quantita, unita, fonte_dato,
        qualita_dato, stato_dato, note, provenance
    FROM raw.scope1_ingestions
    WHERE tenant_id = :tenant_id AND anno = :anno
    """
)

_SELECT_SCOPE2 = text(
    """
    SELECT
        id, tenant_id, anno, codice_sito, voce_s2,
        quantita, unita, strumento_mb, fonte_dato,
        qualita_dato, stato_dato, note, provenance
    FROM raw.scope2_ingestions
    WHERE tenant_id = :tenant_id AND anno = :anno
    """
)

_SELECT_SCOPE3 = text(
    """
    SELECT
        id, tenant_id, anno, categoria_s3, sottocategoria,
        metodo, combustibile, quantita, unita, fonte_dato,
        qualita_dato, stato_dato, note
    FROM raw.scope3_ingestions
    WHERE tenant_id = :tenant_id AND anno = :anno
    """
)

_SELECT_SITES = text(
    """
    SELECT DISTINCT codice_sito
    FROM raw.scope1_ingestions
    WHERE tenant_id = :tenant_id AND anno = :anno
    """
)


def _load_raw_rows(
    engine: Engine,
    *,
    tenant_id: uuid.UUID,
    anno: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], tuple[str, ...]]:
    """Load raw ingestion rows from the three raw tables.

    Args:
        engine: Sync SQLAlchemy engine.
        tenant_id: Tenant UUID filter.
        anno: Reporting year filter.

    Returns:
        Tuple of (scope1_rows, scope2_rows, scope3_rows, sites).
    """
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "anno": anno}

    with engine.connect() as conn:
        scope1_rows = [dict(r._mapping) for r in conn.execute(_SELECT_SCOPE1, params)]
        scope2_rows = [dict(r._mapping) for r in conn.execute(_SELECT_SCOPE2, params)]
        scope3_rows = [dict(r._mapping) for r in conn.execute(_SELECT_SCOPE3, params)]
        site_rows = conn.execute(_SELECT_SITES, params)
        sites = tuple(str(r[0]) for r in site_rows)

    logger.info(
        "raw_rows_loaded",
        tenant_id=str(tenant_id),
        anno=anno,
        scope1=len(scope1_rows),
        scope2=len(scope2_rows),
        scope3=len(scope3_rows),
        sites=len(sites),
    )
    return scope1_rows, scope2_rows, scope3_rows, sites


# ---------------------------------------------------------------------------
# Async persistence helpers
# ---------------------------------------------------------------------------

_INSERT_EMISSION = text(
    """
    INSERT INTO calc.emissions_consolidated (
        id, tenant_id, correlation_id, raw_row_id, raw_scope, scope, sub_scope,
        codice_sito, anno, tco2e, co2_tonne, ch4_tco2e, n2o_tco2e,
        co2_biogenic_tonne, co2_fossil_tonne,
        factor_id, factor_version, factor_source, gwp_set,
        methodology, regulatory_stream, calc_timestamp, created_by,
        valid_from, valid_to, superseded_by, reason_code, disclosure_notes
    ) VALUES (
        :id, :tenant_id, :correlation_id, :raw_row_id, :raw_scope, :scope, :sub_scope,
        :codice_sito, :anno, :tco2e, :co2_tonne, :ch4_tco2e, :n2o_tco2e,
        :co2_biogenic_tonne, :co2_fossil_tonne,
        :factor_id, :factor_version, :factor_source, :gwp_set,
        :methodology, :regulatory_stream, :calc_timestamp, :created_by,
        :valid_from, :valid_to, :superseded_by, :reason_code, :disclosure_notes
    )
    """
)

_INSERT_CALC_RUN = text(
    """
    INSERT INTO ops.calc_runs (
        id, tenant_id, correlation_id, anno,
        emissions_written, duration_ms, gwp_set, regulatory_stream,
        started_at, finished_at, created_by
    ) VALUES (
        :id, :tenant_id, :correlation_id, :anno,
        :emissions_written, :duration_ms, :gwp_set, :regulatory_stream,
        :started_at, :finished_at, :created_by
    )
    """
)


def _emission_to_params(
    record: EmissionRecord,
    *,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    """Convert an EmissionRecord domain object into a dict suitable for Core INSERT.

    The factor_id FK in the DB points to ref.factor_catalog.id (a UUID).
    Priority for resolving the FK UUID (first non-None wins):
      1. ``record.factor_id_uuid`` — set by the orchestrator when it threads
         the DB UUID from the catalog adapter through to the EmissionRecord.
      2. nil UUID sentinel — so the INSERT type never fails with a Python
         error; the DB FK constraint will raise instead, which is correct and
         surfaces as a data-quality bug rather than a silent bad write.

    Args:
        record: Domain emission record.
        tenant_id: Owning tenant UUID.

    Returns:
        Parameter dict for the INSERT statement.
    """
    now = datetime.now(UTC)
    # factor_id_uuid is populated by make_emission() from FactorRecord.factor_db_id.
    # Fall back to nil UUID only as a last resort so the INSERT type never
    # raises a Python error; the FK constraint on the DB side will catch it.
    fk_uuid = record.factor_id_uuid if record.factor_id_uuid is not None else uuid.UUID(int=0)
    return {
        "id": str(record.id),
        "tenant_id": str(tenant_id),
        "correlation_id": str(record.correlation_id),
        "raw_row_id": str(record.raw_row_id) if record.raw_row_id else str(uuid.UUID(int=0)),
        "raw_scope": record.scope,
        "scope": record.scope,
        "sub_scope": record.sub_scope,
        "codice_sito": record.codice_sito,
        "anno": record.anno,
        "tco2e": float(record.tco2e),
        "co2_tonne": float(record.co2_tonne) if record.co2_tonne is not None else None,
        "ch4_tco2e": float(record.ch4_tco2e) if record.ch4_tco2e is not None else None,
        "n2o_tco2e": float(record.n2o_tco2e) if record.n2o_tco2e is not None else None,
        "co2_biogenic_tonne": (
            float(record.co2_biogenic_tonne) if record.co2_biogenic_tonne is not None else None
        ),
        "co2_fossil_tonne": (
            float(record.co2_fossil_tonne) if record.co2_fossil_tonne is not None else None
        ),
        "factor_id": str(fk_uuid),
        "factor_version": record.factor_version,
        "factor_source": record.factor_source,
        "gwp_set": record.gwp_set,
        "methodology": record.methodology,
        "regulatory_stream": record.regulatory_stream,
        "calc_timestamp": record.calc_timestamp,
        "created_by": record.created_by,
        "valid_from": record.valid_from if record.valid_from is not None else now,
        "valid_to": record.valid_to,
        "superseded_by": str(record.superseded_by) if record.superseded_by else None,
        "reason_code": record.reason_code,
        "disclosure_notes": record.disclosure_notes,
    }


async def _persist_emissions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: uuid.UUID,
    correlation_id: uuid.UUID,
    anno: int,
    records: list[EmissionRecord],
    duration_ms: int,
    started_at: datetime,
    gwp_set: str,
    regulatory_stream: str,
    created_by: str,
) -> None:
    """Bulk-INSERT emissions and a single ops.calc_runs row in one transaction.

    Args:
        session_factory: Async sessionmaker for the target database.
        tenant_id: Tenant UUID.
        correlation_id: Run correlation UUID.
        anno: Reporting year.
        records: Emission records to persist.
        duration_ms: Run duration in milliseconds.
        started_at: Wall-clock start of the run (UTC).
        gwp_set: GWP set code used ('AR6' or 'AR5').
        regulatory_stream: Regulatory stream used.
        created_by: Service-account identifier.
    """
    finished_at = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        # Inject RLS GUCs immediately after opening the transaction so that
        # all INSERT statements below see app.tenant_id and app.role_code.
        # The service account writes as esg_manager (PERMISSION_MATRIX key
        # "emissions"/"correct") which is the seeded role that owns bulk
        # calc inserts (rbac.py — ROLE_ESG_MANAGER).
        await set_session_gucs(
            session,
            tenant_id=str(tenant_id),
            role_code="esg_manager",
        )

        if records:
            param_list = [
                _emission_to_params(r, tenant_id=tenant_id) for r in records
            ]
            await session.execute(_INSERT_EMISSION, param_list)

        await session.execute(
            _INSERT_CALC_RUN,
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "correlation_id": str(correlation_id),
                "anno": anno,
                "emissions_written": len(records),
                "duration_ms": duration_ms,
                "gwp_set": gwp_set,
                "regulatory_stream": regulatory_stream,
                "started_at": started_at,
                "finished_at": finished_at,
                "created_by": created_by,
            },
        )

    logger.info(
        "persistence_complete",
        tenant_id=str(tenant_id),
        correlation_id=str(correlation_id),
        emissions_written=len(records),
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_calc_and_persist(
    *,
    tenant_id: uuid.UUID,
    anno: int,
    correlation_id: uuid.UUID,
    sync_engine: Engine,
    async_session_factory: async_sessionmaker[AsyncSession],
    gwp_set: str = "AR6",
    regulatory_stream: str = "CSRD_ESRS_E1",
    created_by: str = "calc_service",
) -> CalcPersistResult:
    """Run the calc pipeline end-to-end and persist the results.

    Steps:
        1. Load raw rows from raw.scope{1,2,3}_ingestions via sync engine.
        2. Build SqlFactorCatalogAdapter (sync) and GWPSetTable.
        3. Run CalcOrchestrator to produce list[EmissionRecord].
        4. Bulk-INSERT into calc.emissions_consolidated via async session.
        5. Insert a single ops.calc_runs audit row.
        6. Return CalcPersistResult.

    Args:
        tenant_id: Tenant UUID.
        anno: Reporting year (e.g. 2025).
        correlation_id: UUID linking all emitted rows to this run.
        sync_engine: Sync SQLAlchemy Engine (psycopg driver).
        async_session_factory: Async sessionmaker for the write step.
        gwp_set: GWP set code ('AR6' or 'AR5'). Defaults to 'AR6' (CSRD).
        regulatory_stream: Regulatory stream tag. Defaults to 'CSRD_ESRS_E1'.
        created_by: Stamped on every emitted row and the calc_runs row.

    Returns:
        CalcPersistResult summary.
    """
    log = logger.bind(
        tenant_id=str(tenant_id),
        anno=anno,
        correlation_id=str(correlation_id),
        gwp_set=gwp_set,
        regulatory_stream=regulatory_stream,
    )
    log.info("calc_run_start")

    started_at = datetime.now(UTC)
    t0 = time.monotonic()

    # Step 1 -- load raw rows
    scope1_rows, scope2_rows, scope3_rows, sites = _load_raw_rows(
        sync_engine, tenant_id=tenant_id, anno=anno
    )

    # Step 2 -- build adapter + GWP table
    catalog = SqlFactorCatalogAdapter(tenant_id, sync_engine=sync_engine)
    from ghg_tool.domain.value_objects.gwp_set import get_gwp_values
    gwp_values = get_gwp_values(gwp_set)  # type: ignore[arg-type]
    gwp_table = GWPSetTable(gwp_values)

    # Step 3 -- run orchestrator
    inputs = CalcRunInputs(
        correlation_id=correlation_id,
        anno=anno,
        sites=sites,
        scope1_rows=tuple(scope1_rows),
        scope2_rows=tuple(scope2_rows),
        scope3_rows=tuple(scope3_rows),
        created_by=created_by,
        regulatory_stream=regulatory_stream,
    )
    orchestrator = CalcOrchestrator(catalog, gwp_table)
    records: list[EmissionRecord] = orchestrator.run(inputs)

    duration_ms = int((time.monotonic() - t0) * 1000)
    log.info("orchestrator_complete", records=len(records), duration_ms=duration_ms)

    # Step 4+5 -- persist via async session
    asyncio.run(
        _persist_emissions(
            async_session_factory,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            anno=anno,
            records=records,
            duration_ms=duration_ms,
            started_at=started_at,
            gwp_set=gwp_set,
            regulatory_stream=regulatory_stream,
            created_by=created_by,
        )
    )

    scope1_count = sum(1 for r in records if r.scope == 1)
    scope2_count = sum(1 for r in records if r.scope == 2)
    scope3_count = sum(1 for r in records if r.scope == 3)

    result = CalcPersistResult(
        emissions_written=len(records),
        scope1_count=scope1_count,
        scope2_count=scope2_count,
        scope3_count=scope3_count,
        duration_ms=duration_ms,
        correlation_id=correlation_id,
    )
    log.info("calc_run_complete", result=result)
    return result
