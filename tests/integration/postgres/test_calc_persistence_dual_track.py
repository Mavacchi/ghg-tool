"""Integration tests: dual_run_id reciprocity + append-only + frozen-pair (Q3).

These tests verify the mechanical enforcement of the Q1.A + Q2 + Q3 decisions:

  Q1.A (sustainability-expert): dual_run_id FK column on ops.calc_runs is
       required for verifier traceability (Reg. UE 2018/2067 Art. 6).
  Q2  (compliance): pre-generated-UUID two-row insert pattern; append-only
       enforced at trigger level; no UPDATE permitted.
  Q3  (requirements): re-running one track creates a NEW pair; existing pair
       is frozen.

REQUIRES a live Postgres testcontainer.  If testcontainers-python is not
installed or Docker is unavailable these tests are skipped automatically via
the ``postgres`` mark + the ``requires_postgres`` fixture.

Mark: pytest.mark.integration (collected only when -m integration or
PYTEST_RUN_INTEGRATION=1 is set in the environment).

Tests that require a real COMMIT (trigger enforcement, reciprocity at commit
time) open their own connections via ``async_engine.begin()`` and TRUNCATE
``ops.calc_runs`` in teardown to avoid cross-test bleed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANNO = 2024
_CREATED_BY = "test_runner"


async def _insert_calc_run(
    engine: AsyncEngine,
    *,
    run_id: uuid.UUID,
    tenant_id: str,
    correlation_id: uuid.UUID,
    regulatory_stream: str,
    gwp_set: str = "AR6",
    dual_run_id: uuid.UUID | None = None,
    anno: int = _ANNO,
) -> None:
    """Insert a minimal ops.calc_runs row via a committed transaction.

    Args:
        engine: AsyncEngine.
        run_id: UUID for the new row.
        tenant_id: Tenant UUID string.
        correlation_id: Correlation UUID.
        regulatory_stream: e.g. 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'.
        gwp_set: GWP set code.
        dual_run_id: UUID of the paired row, or None for single-track.
        anno: Reporting year.
    """
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ops.calc_runs "
                "(id, tenant_id, correlation_id, anno, "
                " emissions_written, duration_ms, gwp_set, "
                " regulatory_stream, started_at, finished_at, "
                " created_by, dual_run_id) "
                "VALUES ("
                " CAST(:id AS uuid), CAST(:tid AS uuid), "
                " CAST(:cid AS uuid), :anno, "
                " 0, 0, :gwp_set, "
                " :regulatory_stream, :now, :now, "
                " :created_by, "
                " CAST(:dual_run_id AS uuid)"
                ")"
            ),
            {
                "id": str(run_id),
                "tid": tenant_id,
                "cid": str(correlation_id),
                "anno": anno,
                "gwp_set": gwp_set,
                "regulatory_stream": regulatory_stream,
                "now": now,
                "created_by": _CREATED_BY,
                "dual_run_id": str(dual_run_id) if dual_run_id is not None else None,
            },
        )


async def _truncate_calc_runs(engine: AsyncEngine) -> None:
    """TRUNCATE ops.calc_runs CASCADE to clean up between tests."""
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE ops.calc_runs CASCADE"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def tenant_id(seed_tenants) -> str:  # type: ignore[no-untyped-def]
    """Return tenant_a UUID string from the session-scoped seed."""
    return seed_tenants.tenant_a


# ---------------------------------------------------------------------------
# test_single_track_dual_run_id_is_null
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_track_dual_run_id_is_null(
    async_engine: AsyncEngine,
    tenant_id: str,
) -> None:
    """Single-track CSRD run must have dual_run_id IS NULL after insert.

    Q2: single-track (CSRD-only) runs continue to INSERT one row with
    dual_run_id = NULL.
    """
    run_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    try:
        await _insert_calc_run(
            async_engine,
            run_id=run_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            regulatory_stream="CSRD_ESRS_E1",
            dual_run_id=None,
        )

        async with async_engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT dual_run_id FROM ops.calc_runs "
                    "WHERE id = CAST(:run_id AS uuid)"
                ),
                {"run_id": str(run_id)},
            )
            result = row.fetchone()

        assert result is not None, "ops.calc_runs row not found"
        assert result[0] is None, (
            f"Expected dual_run_id IS NULL for single-track run, got {result[0]}"
        )
    finally:
        await _truncate_calc_runs(async_engine)


# ---------------------------------------------------------------------------
# test_dual_track_reciprocity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_track_reciprocity(
    async_engine: AsyncEngine,
    tenant_id: str,
) -> None:
    """Dual-track run: both rows reference each other; shared correlation_id.

    Q2 integration test asserting reciprocity post-insert:
    a.dual_run_id = b.id AND b.dual_run_id = a.id
    AND a.regulatory_stream <> b.regulatory_stream
    AND a.tenant_id = b.tenant_id AND a.anno = b.anno
    AND a.correlation_id = b.correlation_id
    """
    csrd_run_id = uuid.uuid4()
    ets_run_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    try:
        # Both rows inserted atomically with pre-set reciprocal dual_run_id values.
        now = datetime.now(UTC)
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ops.calc_runs "
                    "(id, tenant_id, correlation_id, anno, "
                    " emissions_written, duration_ms, gwp_set, "
                    " regulatory_stream, started_at, finished_at, "
                    " created_by, dual_run_id) "
                    "VALUES "
                    "(CAST(:id_a AS uuid), CAST(:tid AS uuid), "
                    " CAST(:cid AS uuid), :anno, "
                    " 0, 0, 'AR6', 'CSRD_ESRS_E1', :now, :now, "
                    " :created_by, CAST(:dual_a AS uuid)), "
                    "(CAST(:id_b AS uuid), CAST(:tid AS uuid), "
                    " CAST(:cid AS uuid), :anno, "
                    " 0, 0, 'AR5', 'EU_ETS_PHASE_IV', :now, :now, "
                    " :created_by, CAST(:dual_b AS uuid))"
                ),
                {
                    "id_a": str(csrd_run_id),
                    "id_b": str(ets_run_id),
                    "tid": tenant_id,
                    "cid": str(correlation_id),
                    "anno": _ANNO,
                    "now": now,
                    "created_by": _CREATED_BY,
                    "dual_a": str(ets_run_id),
                    "dual_b": str(csrd_run_id),
                },
            )

        # Verify reciprocity
        async with async_engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT a.id, a.dual_run_id, a.regulatory_stream, "
                    "       a.tenant_id, a.anno, a.correlation_id "
                    "FROM ops.calc_runs a "
                    "WHERE a.id IN (CAST(:id_a AS uuid), CAST(:id_b AS uuid))"
                    "ORDER BY a.regulatory_stream"
                ),
                {"id_a": str(csrd_run_id), "id_b": str(ets_run_id)},
            )
            result_rows = rows.fetchall()

        assert len(result_rows) == 2, f"Expected 2 rows, got {len(result_rows)}"

        # Order: CSRD_ESRS_E1 < EU_ETS_PHASE_IV alphabetically
        csrd_row = next(r for r in result_rows if r[2] == "CSRD_ESRS_E1")
        ets_row = next(r for r in result_rows if r[2] == "EU_ETS_PHASE_IV")

        # Reciprocity
        assert str(csrd_row[1]) == str(ets_run_id), (
            f"CSRD dual_run_id {csrd_row[1]} != ets_run_id {ets_run_id}"
        )
        assert str(ets_row[1]) == str(csrd_run_id), (
            f"ETS dual_run_id {ets_row[1]} != csrd_run_id {csrd_run_id}"
        )

        # Different regulatory_stream
        assert csrd_row[2] != ets_row[2], "regulatory_stream must differ"

        # Same tenant_id, anno, correlation_id
        assert str(csrd_row[3]) == str(ets_row[3]), "tenant_id must match"
        assert csrd_row[4] == ets_row[4], "anno must match"
        assert str(csrd_row[5]) == str(ets_row[5]), "correlation_id must match"
        assert str(csrd_row[5]) == str(correlation_id), "correlation_id must equal shared value"

    finally:
        await _truncate_calc_runs(async_engine)


# ---------------------------------------------------------------------------
# test_dual_track_update_forbidden
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_track_update_forbidden(
    async_engine: AsyncEngine,
    tenant_id: str,
) -> None:
    """Attempting UPDATE ops.calc_runs SET dual_run_id must raise trigger error.

    Proves the append-only policy is mechanically enforced at the DB layer
    (trg_deny_calc_runs_mutation created by migration 0023_M22).
    """
    run_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    try:
        await _insert_calc_run(
            async_engine,
            run_id=run_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            regulatory_stream="CSRD_ESRS_E1",
            dual_run_id=None,
        )

        with pytest.raises(DBAPIError) as exc_info:
            async with async_engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE ops.calc_runs SET dual_run_id = CAST(:new_id AS uuid) "
                        "WHERE id = CAST(:run_id AS uuid)"
                    ),
                    {"new_id": str(uuid.uuid4()), "run_id": str(run_id)},
                )

        # Verify the error message references the append-only policy
        error_msg = str(exc_info.value).lower()
        assert any(
            kw in error_msg
            for kw in ("append-only", "append_only", "calc_runs", "forbidden", "restrict")
        ), f"Unexpected error message: {exc_info.value}"

    finally:
        await _truncate_calc_runs(async_engine)


# ---------------------------------------------------------------------------
# test_dual_track_delete_forbidden
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dual_track_delete_forbidden(
    async_engine: AsyncEngine,
    tenant_id: str,
) -> None:
    """Attempting DELETE FROM ops.calc_runs must raise trigger error.

    Proves the append-only policy is mechanically enforced at the DB layer
    (trg_deny_calc_runs_mutation created by migration 0023_M22).
    """
    run_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    try:
        await _insert_calc_run(
            async_engine,
            run_id=run_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            regulatory_stream="CSRD_ESRS_E1",
            dual_run_id=None,
        )

        with pytest.raises(DBAPIError) as exc_info:
            async with async_engine.begin() as conn:
                await conn.execute(
                    text(
                        "DELETE FROM ops.calc_runs "
                        "WHERE id = CAST(:run_id AS uuid)"
                    ),
                    {"run_id": str(run_id)},
                )

        error_msg = str(exc_info.value).lower()
        assert any(
            kw in error_msg
            for kw in ("append-only", "append_only", "calc_runs", "forbidden", "restrict")
        ), f"Unexpected error message: {exc_info.value}"

    finally:
        await _truncate_calc_runs(async_engine)


# ---------------------------------------------------------------------------
# test_partial_failure_rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_failure_rollback(
    async_engine: AsyncEngine,
    tenant_id: str,
) -> None:
    """Simulate exception during second INSERT: first INSERT must roll back.

    Proves that no orphan row with dual_run_id IS NULL persists when a
    dual-track insert fails mid-way (Q2 partial-failure test).
    """
    csrd_run_id = uuid.uuid4()
    ets_run_id = uuid.uuid4()
    correlation_id = uuid.uuid4()

    try:
        now = datetime.now(UTC)
        # Attempt to insert two rows in one transaction where the second
        # INSERT will fail due to a violating dual_run_id self-reference
        # (CHECK constraint: dual_run_id IS NULL OR dual_run_id <> id).
        with pytest.raises(DBAPIError):
            async with async_engine.begin() as conn:
                # First INSERT: valid CSRD row with dual_run_id = ets_run_id
                await conn.execute(
                    text(
                        "INSERT INTO ops.calc_runs "
                        "(id, tenant_id, correlation_id, anno, "
                        " emissions_written, duration_ms, gwp_set, "
                        " regulatory_stream, started_at, finished_at, "
                        " created_by, dual_run_id) "
                        "VALUES "
                        "(CAST(:id AS uuid), CAST(:tid AS uuid), "
                        " CAST(:cid AS uuid), :anno, "
                        " 0, 0, 'AR6', 'CSRD_ESRS_E1', :now, :now, "
                        " :created_by, CAST(:dual AS uuid))"
                    ),
                    {
                        "id": str(csrd_run_id),
                        "tid": tenant_id,
                        "cid": str(correlation_id),
                        "anno": _ANNO,
                        "now": now,
                        "created_by": _CREATED_BY,
                        "dual": str(ets_run_id),
                    },
                )
                # Second INSERT: self-referencing row (id = dual_run_id)
                # violates ck_calc_runs_no_self_dual CHECK constraint.
                await conn.execute(
                    text(
                        "INSERT INTO ops.calc_runs "
                        "(id, tenant_id, correlation_id, anno, "
                        " emissions_written, duration_ms, gwp_set, "
                        " regulatory_stream, started_at, finished_at, "
                        " created_by, dual_run_id) "
                        "VALUES "
                        "(CAST(:id AS uuid), CAST(:tid AS uuid), "
                        " CAST(:cid AS uuid), :anno, "
                        " 0, 0, 'AR5', 'EU_ETS_PHASE_IV', :now, :now, "
                        " :created_by, CAST(:dual AS uuid))"
                    ),
                    {
                        # Deliberate self-reference to trigger CHECK violation
                        "id": str(ets_run_id),
                        "tid": tenant_id,
                        "cid": str(correlation_id),
                        "anno": _ANNO,
                        "now": now,
                        "created_by": _CREATED_BY,
                        "dual": str(ets_run_id),  # self-reference: id == dual_run_id
                    },
                )

        # After the failed transaction rolls back, neither row should exist.
        async with async_engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM ops.calc_runs "
                    "WHERE id IN (CAST(:id_a AS uuid), CAST(:id_b AS uuid))"
                ),
                {"id_a": str(csrd_run_id), "id_b": str(ets_run_id)},
            )
            count = rows.scalar()

        assert count == 0, (
            f"Rollback failed: found {count} orphan row(s) after partial-insert failure"
        )

    finally:
        await _truncate_calc_runs(async_engine)


# ---------------------------------------------------------------------------
# test_rerun_creates_new_pair (Q3 frozen-pair)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerun_creates_new_pair(
    async_engine: AsyncEngine,
    tenant_id: str,
) -> None:
    """Re-running one track after an existing pair must create a NEW pair.

    Q3 decision: the prior pair is frozen (append-only).  The original pair
    rows (A1, B1) retain their original dual_run_id values unchanged.

    Sequence:
      1. Insert original pair (A1, B1) with reciprocal dual_run_ids.
      2. Re-run CSRD track → new pair (A2, B2) with new UUIDs and new
         correlation_id (simulated by inserting with different IDs).
      3. Verify A1 and B1 still exist with original dual_run_id values.
    """
    a1_id = uuid.uuid4()
    b1_id = uuid.uuid4()
    a2_id = uuid.uuid4()
    b2_id = uuid.uuid4()
    corr1 = uuid.uuid4()
    corr2 = uuid.uuid4()

    try:
        now = datetime.now(UTC)

        # Insert original pair (A1, B1)
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ops.calc_runs "
                    "(id, tenant_id, correlation_id, anno, "
                    " emissions_written, duration_ms, gwp_set, "
                    " regulatory_stream, started_at, finished_at, "
                    " created_by, dual_run_id) "
                    "VALUES "
                    "(CAST(:id_a AS uuid), CAST(:tid AS uuid), "
                    " CAST(:cid AS uuid), :anno, "
                    " 0, 0, 'AR6', 'CSRD_ESRS_E1', :now, :now, "
                    " :created_by, CAST(:dual_a AS uuid)), "
                    "(CAST(:id_b AS uuid), CAST(:tid AS uuid), "
                    " CAST(:cid AS uuid), :anno, "
                    " 0, 0, 'AR5', 'EU_ETS_PHASE_IV', :now, :now, "
                    " :created_by, CAST(:dual_b AS uuid))"
                ),
                {
                    "id_a": str(a1_id),
                    "id_b": str(b1_id),
                    "tid": tenant_id,
                    "cid": str(corr1),
                    "anno": _ANNO,
                    "now": now,
                    "created_by": _CREATED_BY,
                    "dual_a": str(b1_id),
                    "dual_b": str(a1_id),
                },
            )

        # Re-run: insert a NEW pair (A2, B2) — old pair untouched
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ops.calc_runs "
                    "(id, tenant_id, correlation_id, anno, "
                    " emissions_written, duration_ms, gwp_set, "
                    " regulatory_stream, started_at, finished_at, "
                    " created_by, dual_run_id) "
                    "VALUES "
                    "(CAST(:id_a AS uuid), CAST(:tid AS uuid), "
                    " CAST(:cid AS uuid), :anno, "
                    " 0, 0, 'AR6', 'CSRD_ESRS_E1', :now, :now, "
                    " :created_by, CAST(:dual_a AS uuid)), "
                    "(CAST(:id_b AS uuid), CAST(:tid AS uuid), "
                    " CAST(:cid AS uuid), :anno, "
                    " 0, 0, 'AR5', 'EU_ETS_PHASE_IV', :now, :now, "
                    " :created_by, CAST(:dual_b AS uuid))"
                ),
                {
                    "id_a": str(a2_id),
                    "id_b": str(b2_id),
                    "tid": tenant_id,
                    "cid": str(corr2),
                    "anno": _ANNO,
                    "now": now,
                    "created_by": _CREATED_BY,
                    "dual_a": str(b2_id),
                    "dual_b": str(a2_id),
                },
            )

        # Verify original pair (A1, B1) is unchanged
        async with async_engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, dual_run_id, correlation_id "
                    "FROM ops.calc_runs "
                    "WHERE id IN (CAST(:id_a AS uuid), CAST(:id_b AS uuid)) "
                    "ORDER BY regulatory_stream"
                ),
                {"id_a": str(a1_id), "id_b": str(b1_id)},
            )
            original_rows = rows.fetchall()

        assert len(original_rows) == 2, (
            f"Expected 2 original pair rows, got {len(original_rows)}"
        )

        # Find A1 and B1
        a1_row = next(r for r in original_rows if str(r[0]) == str(a1_id))
        b1_row = next(r for r in original_rows if str(r[0]) == str(b1_id))

        assert str(a1_row[1]) == str(b1_id), (
            f"A1 dual_run_id changed! Expected {b1_id}, got {a1_row[1]}"
        )
        assert str(b1_row[1]) == str(a1_id), (
            f"B1 dual_run_id changed! Expected {a1_id}, got {b1_row[1]}"
        )
        assert str(a1_row[2]) == str(corr1), "A1 correlation_id changed!"
        assert str(b1_row[2]) == str(corr1), "B1 correlation_id changed!"

        # Verify new pair (A2, B2) also exists
        async with async_engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM ops.calc_runs "
                    "WHERE id IN (CAST(:id_a AS uuid), CAST(:id_b AS uuid))"
                ),
                {"id_a": str(a2_id), "id_b": str(b2_id)},
            )
            new_count = rows.scalar()

        assert new_count == 2, f"Expected 2 new pair rows, got {new_count}"

    finally:
        await _truncate_calc_runs(async_engine)
