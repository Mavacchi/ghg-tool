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
    - ops.calc_runs is append-only: no UPDATE or DELETE statement is ever
      issued against this table (Q2 compliance mandate + methodology §7).
    - Dual-track runs insert BOTH rows atomically with pre-generated UUIDs
      (Q2 compliance: pre-generated-UUID two-row insert pattern).
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
from ghg_tool.infrastructure.db.session import set_session_gucs
from ghg_tool.infrastructure.factors.sql_adapter import SqlFactorCatalogAdapter

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Result dataclasses
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
        run_id: The UUID of the ops.calc_runs row.
    """

    emissions_written: int
    scope1_count: int
    scope2_count: int
    scope3_count: int
    duration_ms: int
    correlation_id: uuid.UUID
    run_id: uuid.UUID | None = None


@dataclass(frozen=True)
class DualTrackPersistResult:
    """Summary of an atomic dual-track calc-and-persist run (Q1.A + Q2).

    Both tracks are inserted in a single transaction.  Each track produces
    its own CalcPersistResult; the two runs reference each other via
    dual_run_id.

    Attributes:
        csrd_result: Result for the CSRD / AR6 track.
        ets_result: Result for the EU ETS / AR5 track.
        correlation_id: Shared correlation UUID for both rows (Q2 mandate).
        calc_timestamp: Shared calc_timestamp for both rows (Q2 mandate).
    """

    csrd_result: CalcPersistResult
    ets_result: CalcPersistResult
    correlation_id: uuid.UUID
    calc_timestamp: datetime


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
        started_at, finished_at, created_by, dual_run_id
    ) VALUES (
        :id, :tenant_id, :correlation_id, :anno,
        :emissions_written, :duration_ms, :gwp_set, :regulatory_stream,
        :started_at, :finished_at, :created_by, :dual_run_id
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
        # BUG-03 / Python ID 04 -- Decimal end-to-end. asyncpg and psycopg both
        # bind Python Decimal natively to PostgreSQL NUMERIC, preserving the
        # full precision of the canonical CSRD ledger column. The previous
        # float(...) cast introduced binary-fraction noise on NUMERIC(18,6).
        "tco2e": record.tco2e,
        "co2_tonne": record.co2_tonne,
        "ch4_tco2e": record.ch4_tco2e,
        "n2o_tco2e": record.n2o_tco2e,
        "co2_biogenic_tonne": record.co2_biogenic_tonne,
        "co2_fossil_tonne": record.co2_fossil_tonne,
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
    run_id: uuid.UUID | None = None,
    dual_run_id: uuid.UUID | None = None,
    calc_timestamp: datetime | None = None,
) -> uuid.UUID:
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
        run_id: Pre-generated UUID for the ops.calc_runs row.  When None,
            a new UUID is generated internally.  For dual-track runs the
            caller MUST supply a pre-generated UUID (Q2 mandate).
        dual_run_id: UUID of the paired ops.calc_runs row in a dual-track
            run.  None for single-track runs (Q2: NULL on insert is legal;
            NULL→non-NULL transition via UPDATE is forbidden).
        calc_timestamp: Explicit calc_timestamp to stamp on the calc_runs
            row.  For dual-track pairs the caller supplies the same value
            for both tracks (Q2: correlation_id and calc_timestamp MUST be
            identical across both rows of a pair).

    Returns:
        The UUID of the inserted ops.calc_runs row.
    """
    finished_at = datetime.now(UTC)
    effective_run_id: uuid.UUID = run_id if run_id is not None else uuid.uuid4()
    effective_calc_ts: datetime = calc_timestamp if calc_timestamp is not None else finished_at

    async with session_factory() as session, session.begin():
        # Inject RLS GUCs immediately after opening the transaction so that
        # all INSERT statements below see app.tenant_id and app.role_code.
        # The service account writes as admin (PERMISSION_MATRIX key
        # "emissions"/"correct") which is the seeded role that owns bulk
        # calc inserts (rbac.py — ROLE_ADMIN).
        await set_session_gucs(
            session,
            tenant_id=str(tenant_id),
            role_code="admin",
        )

        if records:
            param_list = [
                _emission_to_params(r, tenant_id=tenant_id) for r in records
            ]
            await session.execute(_INSERT_EMISSION, param_list)

        await session.execute(
            _INSERT_CALC_RUN,
            {
                "id": str(effective_run_id),
                "tenant_id": str(tenant_id),
                "correlation_id": str(correlation_id),
                "anno": anno,
                "emissions_written": len(records),
                "duration_ms": duration_ms,
                "gwp_set": gwp_set,
                "regulatory_stream": regulatory_stream,
                "started_at": started_at,
                "finished_at": effective_calc_ts,
                "created_by": created_by,
                "dual_run_id": str(dual_run_id) if dual_run_id is not None else None,
            },
        )

    logger.info(
        "persistence_complete",
        tenant_id=str(tenant_id),
        correlation_id=str(correlation_id),
        run_id=str(effective_run_id),
        dual_run_id=str(dual_run_id) if dual_run_id is not None else None,
        emissions_written=len(records),
        duration_ms=duration_ms,
    )
    return effective_run_id


async def _persist_dual_track_emissions(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: uuid.UUID,
    # Shared across both rows (Q2 mandate)
    correlation_id: uuid.UUID,
    calc_timestamp: datetime,
    anno: int,
    started_at: datetime,
    created_by: str,
    # Track A (CSRD / AR6)
    csrd_run_id: uuid.UUID,
    csrd_records: list[EmissionRecord],
    csrd_duration_ms: int,
    csrd_gwp_set: str,
    csrd_regulatory_stream: str,
    # Track B (ETS / AR5)
    ets_run_id: uuid.UUID,
    ets_records: list[EmissionRecord],
    ets_duration_ms: int,
    ets_gwp_set: str,
    ets_regulatory_stream: str,
) -> None:
    """Insert BOTH dual-track calc_runs rows atomically in one transaction.

    Both UUIDs are pre-generated by the caller (Q2 mandate: pre-generated-UUID
    two-row insert pattern).  Both rows carry reciprocal dual_run_id values.
    correlation_id and calc_timestamp are identical across both rows.

    The two ops.calc_runs INSERTs are sequential within a single BEGIN/COMMIT
    block; the DEFERRABLE INITIALLY DEFERRED reciprocity trigger fires at
    COMMIT when both rows are already present, avoiding chicken-and-egg FK
    violations.

    No UPDATE statement is issued at any point.  NULL→non-NULL transitions
    via UPDATE are forbidden (Q2 mandate + methodology §7 append-only).

    Args:
        session_factory: Async sessionmaker.
        tenant_id: Tenant UUID.
        correlation_id: Shared correlation UUID for both rows.
        calc_timestamp: Shared calc_timestamp for both rows.
        anno: Reporting year.
        started_at: Wall-clock start of the combined run.
        created_by: Service-account identifier.
        csrd_run_id: Pre-generated UUID for the CSRD calc_runs row.
        csrd_records: Emission records for the CSRD track.
        csrd_duration_ms: Duration for the CSRD orchestrator run.
        csrd_gwp_set: GWP set for CSRD (typically AR6).
        csrd_regulatory_stream: Regulatory stream for CSRD.
        ets_run_id: Pre-generated UUID for the ETS calc_runs row.
        ets_records: Emission records for the ETS track.
        ets_duration_ms: Duration for the ETS orchestrator run.
        ets_gwp_set: GWP set for ETS (typically AR5).
        ets_regulatory_stream: Regulatory stream for ETS.
    """
    async with session_factory() as session, session.begin():
        await set_session_gucs(
            session,
            tenant_id=str(tenant_id),
            role_code="admin",
        )

        # Insert CSRD emission rows
        if csrd_records:
            await session.execute(
                _INSERT_EMISSION,
                [_emission_to_params(r, tenant_id=tenant_id) for r in csrd_records],
            )

        # Insert ETS emission rows
        if ets_records:
            await session.execute(
                _INSERT_EMISSION,
                [_emission_to_params(r, tenant_id=tenant_id) for r in ets_records],
            )

        # Insert CSRD calc_runs row with dual_run_id pointing to ETS row
        await session.execute(
            _INSERT_CALC_RUN,
            {
                "id": str(csrd_run_id),
                "tenant_id": str(tenant_id),
                "correlation_id": str(correlation_id),
                "anno": anno,
                "emissions_written": len(csrd_records),
                "duration_ms": csrd_duration_ms,
                "gwp_set": csrd_gwp_set,
                "regulatory_stream": csrd_regulatory_stream,
                "started_at": started_at,
                "finished_at": calc_timestamp,
                "created_by": created_by,
                "dual_run_id": str(ets_run_id),
            },
        )

        # Insert ETS calc_runs row with dual_run_id pointing to CSRD row
        await session.execute(
            _INSERT_CALC_RUN,
            {
                "id": str(ets_run_id),
                "tenant_id": str(tenant_id),
                "correlation_id": str(correlation_id),
                "anno": anno,
                "emissions_written": len(ets_records),
                "duration_ms": ets_duration_ms,
                "gwp_set": ets_gwp_set,
                "regulatory_stream": ets_regulatory_stream,
                "started_at": started_at,
                "finished_at": calc_timestamp,
                "created_by": created_by,
                "dual_run_id": str(csrd_run_id),
            },
        )
        # Single COMMIT here: DEFERRABLE INITIALLY DEFERRED reciprocity
        # trigger fires now, finding both rows present.  No UPDATE issued.

    logger.info(
        "dual_track_persistence_complete",
        tenant_id=str(tenant_id),
        correlation_id=str(correlation_id),
        csrd_run_id=str(csrd_run_id),
        ets_run_id=str(ets_run_id),
        csrd_emissions_written=len(csrd_records),
        ets_emissions_written=len(ets_records),
    )


# ---------------------------------------------------------------------------
# Public entry points
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
    dual_run_id: uuid.UUID | None = None,
) -> CalcPersistResult:
    """Run the calc pipeline end-to-end and persist the results.

    Steps:
        1. Load raw rows from raw.scope{1,2,3}_ingestions via sync engine.
        2. Build SqlFactorCatalogAdapter (sync) and GWPSetTable.
        3. Run CalcOrchestrator to produce list[EmissionRecord].
        4. Bulk-INSERT into calc.emissions_consolidated via async session.
        5. Insert a single ops.calc_runs audit row (append-only, no UPDATE).
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
        dual_run_id: UUID of the paired ops.calc_runs row.  None for
            single-track runs (Q2: NULL on insert is legal; NULL→non-NULL
            transition via UPDATE is forbidden).

    Returns:
        CalcPersistResult summary.
    """
    log = logger.bind(
        tenant_id=str(tenant_id),
        anno=anno,
        correlation_id=str(correlation_id),
        gwp_set=gwp_set,
        regulatory_stream=regulatory_stream,
        dual_run_id=str(dual_run_id) if dual_run_id is not None else None,
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

    # Step 4+5 -- persist via async session (append-only, no UPDATE)
    effective_run_id = asyncio.run(
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
            dual_run_id=dual_run_id,
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
        run_id=effective_run_id,
    )
    log.info("calc_run_complete", result=result)
    return result


def run_dual_track_and_persist(
    *,
    tenant_id: uuid.UUID,
    anno: int,
    sync_engine: Engine,
    async_session_factory: async_sessionmaker[AsyncSession],
    csrd_gwp_set: str = "AR6",
    csrd_regulatory_stream: str = "CSRD_ESRS_E1",
    ets_gwp_set: str = "AR5",
    ets_regulatory_stream: str = "EU_ETS_PHASE_IV",
    created_by: str = "calc_service",
) -> DualTrackPersistResult:
    """Run BOTH calc tracks atomically and persist the results (Q1.A + Q2).

    Implements the pre-generated-UUID two-row insert pattern mandated by
    compliance Q2:

    1. Generate BOTH run UUIDs in Python via uuid.uuid4() BEFORE any DB call.
    2. Generate a single shared correlation_id and calc_timestamp for both rows.
    3. Run CSRD orchestrator (AR6 / CSRD_ESRS_E1).
    4. Run ETS orchestrator (AR5 / EU_ETS_PHASE_IV).
    5. Insert ALL rows (emissions + both calc_runs) in a SINGLE transaction
       with pre-set reciprocal dual_run_id values.
    6. No UPDATE is ever issued.

    Q3 (frozen-pair): re-running a track when a pair already exists creates
    a NEW pair (new UUIDs, new correlation_id, new calc_timestamp).  The
    existing pair is untouched because ops.calc_runs is append-only.

    Args:
        tenant_id: Tenant UUID.
        anno: Reporting year.
        sync_engine: Sync SQLAlchemy Engine for raw row loading.
        async_session_factory: Async sessionmaker for the write step.
        csrd_gwp_set: GWP set for CSRD track. Defaults to 'AR6'.
        csrd_regulatory_stream: Stream tag for CSRD. Defaults to 'CSRD_ESRS_E1'.
        ets_gwp_set: GWP set for ETS track. Defaults to 'AR5'.
        ets_regulatory_stream: Stream tag for ETS. Defaults to 'EU_ETS_PHASE_IV'.
        created_by: Stamped on every emitted row and both calc_runs rows.

    Returns:
        DualTrackPersistResult containing both CalcPersistResults.
    """
    # Q2 mandate: generate BOTH UUIDs in Python BEFORE any DB call.
    csrd_run_id: uuid.UUID = uuid.uuid4()
    ets_run_id: uuid.UUID = uuid.uuid4()

    # Q2 mandate: correlation_id and calc_timestamp MUST be identical across
    # both rows of a pair.
    shared_correlation_id: uuid.UUID = uuid.uuid4()
    shared_calc_timestamp: datetime = datetime.now(UTC)

    log = logger.bind(
        tenant_id=str(tenant_id),
        anno=anno,
        correlation_id=str(shared_correlation_id),
        csrd_run_id=str(csrd_run_id),
        ets_run_id=str(ets_run_id),
    )
    log.info("dual_track_run_start")

    started_at = datetime.now(UTC)

    # Load raw rows once (both tracks share the same snapshot -- methodology §11.1)
    scope1_rows, scope2_rows, scope3_rows, sites = _load_raw_rows(
        sync_engine, tenant_id=tenant_id, anno=anno
    )

    # Build adapters and GWP tables for both tracks
    catalog = SqlFactorCatalogAdapter(tenant_id, sync_engine=sync_engine)
    from ghg_tool.domain.value_objects.gwp_set import get_gwp_values

    csrd_gwp_values = get_gwp_values(csrd_gwp_set)  # type: ignore[arg-type]
    csrd_gwp_table = GWPSetTable(csrd_gwp_values)
    ets_gwp_values = get_gwp_values(ets_gwp_set)  # type: ignore[arg-type]
    ets_gwp_table = GWPSetTable(ets_gwp_values)

    # Run CSRD orchestrator
    t0_csrd = time.monotonic()
    csrd_inputs = CalcRunInputs(
        correlation_id=shared_correlation_id,
        anno=anno,
        sites=sites,
        scope1_rows=tuple(scope1_rows),
        scope2_rows=tuple(scope2_rows),
        scope3_rows=tuple(scope3_rows),
        created_by=created_by,
        regulatory_stream=csrd_regulatory_stream,
    )
    csrd_orchestrator = CalcOrchestrator(catalog, csrd_gwp_table)
    csrd_records: list[EmissionRecord] = csrd_orchestrator.run(csrd_inputs)
    csrd_duration_ms = int((time.monotonic() - t0_csrd) * 1000)

    # Run ETS orchestrator
    t0_ets = time.monotonic()
    ets_inputs = CalcRunInputs(
        correlation_id=shared_correlation_id,
        anno=anno,
        sites=sites,
        scope1_rows=tuple(scope1_rows),
        scope2_rows=tuple(scope2_rows),
        scope3_rows=tuple(scope3_rows),
        created_by=created_by,
        regulatory_stream=ets_regulatory_stream,
    )
    ets_orchestrator = CalcOrchestrator(catalog, ets_gwp_table)
    ets_records: list[EmissionRecord] = ets_orchestrator.run(ets_inputs)
    ets_duration_ms = int((time.monotonic() - t0_ets) * 1000)

    log.info(
        "dual_track_orchestrators_complete",
        csrd_records=len(csrd_records),
        ets_records=len(ets_records),
    )

    # Persist atomically: both calc_runs rows + all emissions in ONE transaction.
    # No UPDATE is issued at any point (Q2 mandate + methodology §7).
    asyncio.run(
        _persist_dual_track_emissions(
            async_session_factory,
            tenant_id=tenant_id,
            correlation_id=shared_correlation_id,
            calc_timestamp=shared_calc_timestamp,
            anno=anno,
            started_at=started_at,
            created_by=created_by,
            csrd_run_id=csrd_run_id,
            csrd_records=csrd_records,
            csrd_duration_ms=csrd_duration_ms,
            csrd_gwp_set=csrd_gwp_set,
            csrd_regulatory_stream=csrd_regulatory_stream,
            ets_run_id=ets_run_id,
            ets_records=ets_records,
            ets_duration_ms=ets_duration_ms,
            ets_gwp_set=ets_gwp_set,
            ets_regulatory_stream=ets_regulatory_stream,
        )
    )

    def _make_result(
        records: list[EmissionRecord],
        run_id: uuid.UUID,
        duration_ms: int,
    ) -> CalcPersistResult:
        return CalcPersistResult(
            emissions_written=len(records),
            scope1_count=sum(1 for r in records if r.scope == 1),
            scope2_count=sum(1 for r in records if r.scope == 2),
            scope3_count=sum(1 for r in records if r.scope == 3),
            duration_ms=duration_ms,
            correlation_id=shared_correlation_id,
            run_id=run_id,
        )

    result = DualTrackPersistResult(
        csrd_result=_make_result(csrd_records, csrd_run_id, csrd_duration_ms),
        ets_result=_make_result(ets_records, ets_run_id, ets_duration_ms),
        correlation_id=shared_correlation_id,
        calc_timestamp=shared_calc_timestamp,
    )
    log.info("dual_track_run_complete", result=result)
    return result
