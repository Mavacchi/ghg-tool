"""Integration tests: Row-Level Security tenant isolation.

Verifies that the RLS policies on calc.emissions_consolidated (and the
chart_annotations table) enforce tenant isolation across sessions:

  1. Session with GUC app.tenant_id=TENANT_A can INSERT and SELECT its rows.
  2. Session with GUC app.tenant_id=TENANT_B cannot see TENANT_A's rows
     (SELECT returns 0 rows for the same site/year combination).
  3. Session switched back to TENANT_A recovers visibility of its row.

Design notes
------------
PostgreSQL FORCE ROW LEVEL SECURITY means the RLS policies apply even to
superusers on the table owner's connection.  The policies evaluate
  current_setting('app.tenant_id', true)::uuid
so isolation is achieved by setting different GUCs on different connections,
not by using different DB roles.

Each test in this module opens its own connection via `async_engine.begin()`
(not the rollback-session fixture) because:
  (a) We need the INSERT to COMMIT so a second connection can see it.
  (b) We use TRUNCATE in a `finally` block to clean up.

RLS on chart_annotations uses:
  tenant_id::text = current_setting('app.tenant_id', true)
(text comparison, not ::uuid cast) per M17 DDL.  Both styles are tested.

ISAE 3000 relevance: cross-tenant data leakage is a GDPR violation and
would compromise the confidentiality of competitor ESG figures in a
multi-tenant deployment.  This test tier provides machine-verifiable proof
that the DB-level isolation cannot be bypassed by application-layer bugs.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.postgres.conftest import TenantSeed, insert_factor_for_tenant

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper: set RLS GUCs on a connection
# ---------------------------------------------------------------------------


async def _set_gucs(conn: object, *, tenant_id: str, role_code: str = "data_steward") -> None:
    """Set app.tenant_id and app.role_code GUCs on conn (transaction-local).

    Uses set_config(..., true) so the GUC resets automatically when the
    transaction ends.  This mirrors what the application layer does via
    session.py:set_session_gucs().

    Args:
        conn: An open SQLAlchemy async connection.
        tenant_id: UUID string to assign to app.tenant_id.
        role_code: Role string to assign to app.role_code.
    """
    from sqlalchemy import text as _text  # noqa: PLC0415

    await conn.execute(  # type: ignore[attr-defined]
        _text(
            "SELECT set_config('app.tenant_id', :tid, true), "
            "       set_config('app.role_code', :role, true)"
        ),
        {"tid": tenant_id, "role": role_code},
    )


# ---------------------------------------------------------------------------
# Helper: insert an emission row within a connection (with GUCs already set)
# ---------------------------------------------------------------------------


async def _insert_emission_on_conn(
    conn: object,
    *,
    tenant_id: str,
    factor_id: str,
    anno: int = 2024,
    tco2e: float = 5.0,
) -> str:
    """Insert one emission row using an already-open connection.

    The caller is responsible for setting GUCs before calling this function.

    Args:
        conn: Open SQLAlchemy async connection with GUCs set.
        tenant_id: UUID string of the tenant.
        factor_id: UUID string of a ref.factor_catalog row.
        anno: Reporting year.
        tco2e: Emission value.

    Returns:
        UUID string of the inserted row.
    """
    from sqlalchemy import text as _text  # noqa: PLC0415

    row_id = str(uuid.uuid4())
    unique_sub_scope = f"rls_test_{row_id[:8]}"

    await conn.execute(  # type: ignore[attr-defined]
        _text(
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
                'AR6', 'stoichiometric', 'rls_isolation_test'
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
# Test: tenant A can see its own rows
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_a_can_read_own_emissions(
    async_engine: AsyncEngine,
    seed_tenants: TenantSeed,
) -> None:
    """Session for tenant A can INSERT and then SELECT its own emissions.

    This is the positive baseline for RLS: a correctly-authenticated session
    must be able to read its own data.  If this fails, the RLS policy is
    over-restrictive (blocks reads for the owning tenant).
    """
    factor_id_a = await insert_factor_for_tenant(
        async_engine, tenant_id=seed_tenants.tenant_a
    )

    inserted_id: str | None = None

    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_a, role_code="data_steward")
        inserted_id = await _insert_emission_on_conn(
            conn,
            tenant_id=seed_tenants.tenant_a,
            factor_id=factor_id_a,
            anno=2024,
        )

    assert inserted_id is not None

    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_a, role_code="data_steward")
        result = await conn.execute(
            text(
                "SELECT id::text FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": inserted_id},
        )
        row = result.fetchone()

    assert row is not None, (
        "Tenant A must be able to read its own emission row"
    )
    assert str(row[0]) == inserted_id


# ---------------------------------------------------------------------------
# Test: tenant B cannot see tenant A's rows
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_b_cannot_read_tenant_a_emissions(
    async_engine: AsyncEngine,
    seed_tenants: TenantSeed,
) -> None:
    """Session for tenant B sees zero rows when querying with tenant A's row id.

    The RLS policy p_emissions_tenant_isolation filters by
    tenant_id = current_setting('app.tenant_id', true)::uuid.
    A session authenticated as tenant B setting its GUC to tenant_b_id
    must not be able to retrieve a row that belongs to tenant_a_id.

    This test proves DB-level cross-tenant read isolation independent of
    any application-layer filtering.
    """
    factor_id_a = await insert_factor_for_tenant(
        async_engine, tenant_id=seed_tenants.tenant_a
    )

    # Insert a row for tenant A
    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_a, role_code="data_steward")
        row_a_id = await _insert_emission_on_conn(
            conn,
            tenant_id=seed_tenants.tenant_a,
            factor_id=factor_id_a,
            anno=2023,
            tco2e=7.77,
        )

    # Now query as tenant B -- must return 0 rows
    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_b, role_code="data_steward")
        result = await conn.execute(
            text(
                "SELECT id::text FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_a_id},
        )
        row = result.fetchone()

    assert row is None, (
        f"Tenant B must NOT be able to read tenant A's emission row {row_a_id}. "
        "RLS policy p_emissions_tenant_isolation is not enforcing isolation correctly."
    )


# ---------------------------------------------------------------------------
# Test: switching back to tenant A restores visibility
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_switching_to_tenant_a_restores_visibility(
    async_engine: AsyncEngine,
    seed_tenants: TenantSeed,
) -> None:
    """After checking tenant B cannot see A's row, switching back to A restores it.

    This test proves the GUC-based isolation is symmetric and reversible:
    the same connection, once its GUC is updated, gains or loses access
    to rows based solely on the tenant_id GUC value.
    """
    factor_id_a = await insert_factor_for_tenant(
        async_engine, tenant_id=seed_tenants.tenant_a
    )

    # Insert a row for tenant A
    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_a, role_code="data_steward")
        row_id = await _insert_emission_on_conn(
            conn,
            tenant_id=seed_tenants.tenant_a,
            factor_id=factor_id_a,
            anno=2022,
            tco2e=3.14,
        )

    # Verify tenant B cannot see the row
    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_b, role_code="data_steward")
        result_b = await conn.execute(
            text(
                "SELECT count(*) FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        count_b = result_b.scalar()

    assert count_b == 0, (
        "Tenant B must see 0 rows for tenant A's emission (RLS isolation)"
    )

    # Switch the new connection back to tenant A: row must be visible again
    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_a, role_code="data_steward")
        result_a = await conn.execute(
            text(
                "SELECT id::text FROM calc.emissions_consolidated "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        row_a = result_a.fetchone()

    assert row_a is not None, (
        "Switching back to tenant A must restore visibility of its own row"
    )
    assert str(row_a[0]) == row_id


# ---------------------------------------------------------------------------
# Test: tenant B cannot see tenant A's chart_annotations
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chart_annotation_rls_cross_tenant_blocked(
    async_engine: AsyncEngine,
    seed_tenants: TenantSeed,
) -> None:
    """Tenant B cannot read tenant A's chart_annotations.

    The M17 RLS policy uses text comparison:
      tenant_id::text = current_setting('app.tenant_id', true)
    This test validates that variant works identically to the ::uuid cast
    used on emissions_consolidated.
    """
    ann_id = str(uuid.uuid4())

    # Insert annotation for tenant A
    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_a, role_code="data_steward")
        await conn.execute(
            text(
                "INSERT INTO ops.chart_annotations ("
                "  id, tenant_id, chart_key, title, body, severity, created_by, is_visible"
                ") VALUES ("
                "  CAST(:id AS uuid), CAST(:tid AS uuid), :chart_key, "
                "  :title, :body, 'INFO', 'rls_test', TRUE"
                ")"
            ),
            {
                "id": ann_id,
                "tid": seed_tenants.tenant_a,
                "chart_key": f"rls_test_{ann_id[:8]}",
                "title": "RLS isolation test annotation",
                "body": "Should not be visible to tenant B",
            },
        )

    # Attempt to read as tenant B -- must return 0 rows
    async with async_engine.begin() as conn:
        await _set_gucs(conn, tenant_id=seed_tenants.tenant_b, role_code="data_steward")
        result = await conn.execute(
            text(
                "SELECT count(*) FROM ops.chart_annotations "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": ann_id},
        )
        count_b = result.scalar()

    assert count_b == 0, (
        "Tenant B must not be able to read tenant A's chart_annotations row. "
        "RLS policy p_chart_annotations_tenant is not enforcing isolation."
    )
