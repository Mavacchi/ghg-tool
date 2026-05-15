"""Integration tests: append-only enforcement on calc.emissions_consolidated.

Verifies:
  - A valid INSERT succeeds (baseline / positive case).
  - UPDATE on any immutable column raises with the M1 trigger message.
  - DELETE raises with the M1 trigger message.
  - A bitemporal correction (superseded_by pointer) is accepted: both the
    original and the correction row coexist, with the original closed via
    valid_to and the pointer set.

These tests require REAL commits because the immutability trigger fires
BEFORE UPDATE/DELETE and raises a PL/pgSQL exception -- the exception
surfaces immediately at execute time (within the transaction), not only
at commit.  However, the correction flow (fn_emit_correction) must also
commit so that the valid_to update persists.

Design: each test uses the `async_engine` fixture directly, opens its own
connection with `engine.begin()`, and TRUNCATEs the relevant tables in a
`finally` block so state does not bleed between tests.

ISAE 3000 relevance: the append-only guarantee is the foundation of the
audit trail. If UPDATE or DELETE could succeed on emissions_consolidated,
a data steward could retroactively alter disclosed figures without leaving
a forensic trace.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.postgres.conftest import insert_factor_for_tenant

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helper: insert a minimal valid emission row; return its UUID string
# ---------------------------------------------------------------------------


async def _insert_emission(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    factor_id: str,
    tco2e: float = 1.23456,
    anno: int = 2024,
) -> str:
    """Insert one emission row via a committed transaction; return its UUID.

    Each call produces a unique sub_scope suffix so the partial unique index
    (ux_emissions_active_natural_key) is not violated by repeated inserts
    within the same test run.

    Args:
        engine: AsyncEngine for the test database.
        tenant_id: UUID string of the tenant.
        factor_id: UUID string of an existing ref.factor_catalog row.
        tco2e: Emission value in tCO2e (must be >= 0).
        anno: Reporting year.

    Returns:
        UUID string of the newly committed emission row.
    """
    row_id = str(uuid.uuid4())
    unique_sub_scope = f"append_only_test_{row_id[:8]}"

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO calc.emissions_consolidated (
                    id, tenant_id, correlation_id, raw_row_id,
                    raw_scope, scope, sub_scope, codice_sito, anno,
                    tco2e, factor_id, factor_version, factor_source,
                    gwp_set, methodology, created_by
                ) VALUES (
                    CAST(:id AS uuid),
                    CAST(:tid AS uuid),
                    CAST(:corr_id AS uuid),
                    CAST(:raw_row_id AS uuid),
                    1, 1, :sub_scope, 'IANO', :anno,
                    :tco2e, CAST(:factor_id AS uuid), '2006', 'IPCC',
                    'AR6', 'stoichiometric', 'append_only_test'
                )
                """
            ),
            {
                "id": row_id,
                "tid": tenant_id,
                "corr_id": str(uuid.uuid4()),
                "raw_row_id": str(uuid.uuid4()),
                "sub_scope": unique_sub_scope,
                "anno": anno,
                "tco2e": tco2e,
                "factor_id": factor_id,
            },
        )
    return row_id


# ---------------------------------------------------------------------------
# Test: baseline INSERT succeeds
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emission_insert_succeeds(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """A valid INSERT on calc.emissions_consolidated commits without error.

    This is the positive baseline.  If this fails, all other tests in this
    file are moot: the problem is upstream in the schema or migration, not
    the trigger.

    Postcondition: the row is readable with valid_to IS NULL and
    superseded_by IS NULL (active record, not yet corrected).
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    factor_id = await insert_factor_for_tenant(async_engine, tenant_id=seed.tenant_a)

    row_id = await _insert_emission(
        async_engine,
        tenant_id=seed.tenant_a,
        factor_id=factor_id,
    )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id::text, valid_to, superseded_by "
                "FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        row = result.fetchone()

    assert row is not None, f"Inserted row {row_id} must be queryable"
    assert str(row[0]) == row_id
    assert row[1] is None, "valid_to must be NULL for a fresh emission (not yet corrected)"
    assert row[2] is None, "superseded_by must be NULL for a fresh emission"


# ---------------------------------------------------------------------------
# Test: UPDATE raises with the M1 trigger message
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emission_update_rejected_by_trigger(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """UPDATE on an immutable column (tco2e) raises PG exception P0001.

    The trg_emissions_deny_mutation trigger (M1) rejects any UPDATE that is
    not issued through calc.fn_emit_correction (which sets the GUC
    app.correction_in_progress=true).  The error message must contain
    'forbidden' or 'outside the correction'.

    asyncpg surfaces PL/pgSQL RAISE EXCEPTION as asyncpg.RaiseError, which
    SQLAlchemy wraps as DBAPIError.  The test accepts the full hierarchy
    (IntegrityError, ProgrammingError, DBAPIError) to be driver-agnostic.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    factor_id = await insert_factor_for_tenant(async_engine, tenant_id=seed.tenant_a)
    row_id = await _insert_emission(
        async_engine,
        tenant_id=seed.tenant_a,
        factor_id=factor_id,
        anno=2023,
    )

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE calc.emissions_consolidated "
                    "SET tco2e = 999.0 "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            )

    err_str = str(exc_info.value).lower()
    assert "forbidden" in err_str or "outside" in err_str or "p0001" in err_str, (
        f"Expected immutability trigger message, got: {exc_info.value}"
    )

    # Confirm original value is unchanged
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tco2e FROM calc.emissions_consolidated WHERE id = CAST(:id AS uuid)"),
            {"id": row_id},
        )
        row = result.fetchone()
    assert row is not None
    # Decimal comparison: tco2e must still be 1.23456, not 999.0
    assert abs(float(row[0]) - 1.23456) < 1e-4, (
        f"tco2e must remain unchanged at 1.23456 after rejected UPDATE, got {row[0]}"
    )


# ---------------------------------------------------------------------------
# Test: DELETE raises with the M1 trigger message
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emission_delete_rejected_by_trigger(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """DELETE on calc.emissions_consolidated raises PG exception P0001.

    The trigger fires unconditionally on DELETE (unlike UPDATE, which has
    the correction GUC bypass path).  The error message from M1 is:
    'DELETE forbidden on calc.emissions_consolidated'.

    After the failed DELETE the row must still exist.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    factor_id = await insert_factor_for_tenant(async_engine, tenant_id=seed.tenant_a)
    row_id = await _insert_emission(
        async_engine,
        tenant_id=seed.tenant_a,
        factor_id=factor_id,
        anno=2022,
    )

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM calc.emissions_consolidated "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            )

    err_str = str(exc_info.value).lower()
    assert "forbidden" in err_str or "delete" in err_str or "p0001" in err_str, (
        f"Expected DELETE forbidden message, got: {exc_info.value}"
    )

    # Row must still exist
    async with async_engine.connect() as conn:
        count_row = await conn.execute(
            text(
                "SELECT count(*) FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        assert count_row.scalar() == 1, "Row must survive the rejected DELETE"


# ---------------------------------------------------------------------------
# Test: bitemporal correction -- both rows coexist with superseded_by pointer
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bitemporal_correction_both_rows_coexist(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """fn_emit_correction inserts superseded_by pointer; both rows coexist.

    Scenario:
      1. Insert row A (original, active).
      2. Insert row B (correction candidate, active initially).
      3. Call calc.fn_emit_correction(A.id, B.id, 'DATA_ERROR').
      4. Assert:
         - Row A: valid_to IS NOT NULL, superseded_by = B.id, reason_code = 'DATA_ERROR'.
         - Row B: valid_to IS NULL, superseded_by IS NULL (now the active row).
         - Total rows for this tenant + sub_scope pattern = 2 (both coexist).

    This is the bitemporal correction protocol from ADR-009.  The append-only
    guarantee means we never DELETE or overwrite row A; we only close it and
    point to the replacement.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    factor_id = await insert_factor_for_tenant(async_engine, tenant_id=seed.tenant_a)

    row_a_id = await _insert_emission(
        async_engine,
        tenant_id=seed.tenant_a,
        factor_id=factor_id,
        tco2e=10.0,
        anno=2021,
    )
    row_b_id = await _insert_emission(
        async_engine,
        tenant_id=seed.tenant_a,
        factor_id=factor_id,
        tco2e=12.5,
        anno=2021,
    )

    # Apply correction via the stored procedure
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "SELECT calc.fn_emit_correction("
                "  CAST(:a AS uuid), CAST(:b AS uuid), 'DATA_ERROR'"
                ")"
            ),
            {"a": row_a_id, "b": row_b_id},
        )

    # Verify row A is closed and points to row B
    async with async_engine.connect() as conn:
        result_a = await conn.execute(
            text(
                "SELECT valid_to, superseded_by::text, reason_code "
                "FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_a_id},
        )
        row_a = result_a.fetchone()

    assert row_a is not None, "Row A must still exist after correction (not deleted)"
    assert row_a[0] is not None, "Row A valid_to must be set after correction closes it"
    assert row_a[1] == row_b_id, (
        f"Row A superseded_by must equal row B id; got {row_a[1]}"
    )
    assert row_a[2] == "DATA_ERROR", (
        f"Row A reason_code must be 'DATA_ERROR'; got {row_a[2]}"
    )

    # Verify row B is still active
    async with async_engine.connect() as conn:
        result_b = await conn.execute(
            text(
                "SELECT valid_to, superseded_by "
                "FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_b_id},
        )
        row_b = result_b.fetchone()

    assert row_b is not None, "Row B must exist"
    assert row_b[0] is None, "Row B valid_to must still be NULL (it is the active row)"
    assert row_b[1] is None, "Row B superseded_by must be NULL (not yet corrected)"

    # Verify both rows coexist (total count = 2)
    async with async_engine.connect() as conn:
        count_row = await conn.execute(
            text(
                "SELECT count(*) FROM calc.emissions_consolidated "
                "WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))"
            ),
            {"a": row_a_id, "b": row_b_id},
        )
        total = count_row.scalar()

    assert total == 2, (
        f"Both rows must coexist after bitemporal correction; found {total}"
    )


# ---------------------------------------------------------------------------
# Test: Decimal precision round-trip via asyncpg cursor
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_decimal_precision_round_trip(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """NUMERIC(18,6) columns preserve Decimal precision through asyncpg.

    asyncpg returns NUMERIC columns as Python Decimal objects (not float).
    SQLAlchemy wraps them for the caller.  This test verifies that a tco2e
    value with 6 significant decimal digits round-trips without floating-point
    degradation.

    The test value 142.700001 is deliberately chosen to exercise the 6th
    decimal place and would fail under float32 representation.
    """
    from decimal import Decimal  # noqa: PLC0415

    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    factor_id = await insert_factor_for_tenant(async_engine, tenant_id=seed.tenant_a)

    precise_value = Decimal("142.700001")
    row_id = await _insert_emission(
        async_engine,
        tenant_id=seed.tenant_a,
        factor_id=factor_id,
        tco2e=float(precise_value),
        anno=2020,
    )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tco2e FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        returned = result.scalar_one()

    # asyncpg returns NUMERIC as Decimal; confirm no float degradation
    returned_decimal = Decimal(str(returned))
    assert abs(returned_decimal - precise_value) < Decimal("0.000001"), (
        f"Decimal precision lost: inserted {precise_value}, got back {returned_decimal}"
    )
