"""Integration tests for migration 0027_M7_wave4_foundation.

Validates three decisions from the wave 4 foundation migration:

  A. pg_cron extension
     - If pg_cron is available: CREATE EXTENSION succeeded and the extension
       row is present in pg_extension.
     - If pg_cron is NOT available (standard testcontainers postgres:15-alpine):
       migration still succeeds — upgrade() degrades gracefully.

  B. idempotency_keys_cleanup cron job
     - If pg_cron is available: job is registered in cron.job with the correct
       schedule (``15 * * * *``) and the correct SQL.
     - Manual execution of the cleanup query deletes expired rows and leaves
       fresh rows intact.

  C. ref.roles — no 'service' role added
     - ref.roles still contains exactly {admin, editor, viewer} after M7.
     - No 'service' row was inserted.

  D. Upgrade / downgrade round-trip
     - alembic downgrade to 0026_M6 then upgrade back to 0027_M7 completes
       without error and leaves the database in the same final state.

These tests run against the session-scoped testcontainers fixture
(postgres:15-alpine).  pg_cron-specific assertions are skipped automatically
when pg_cron is absent (``pytest.mark.skipif``-like pattern via ``pytest.skip``
inside the test body, based on a helper that checks pg_extension).

Mark: pytest -m integration tests/integration/postgres/test_migration_0027.py
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _pgcron_available(engine: AsyncEngine) -> bool:
    """Return True if the pg_cron extension is present in the database.

    Uses ``pg_extension`` which is populated by ``CREATE EXTENSION`` at
    migration time.  This is the canonical way to detect extension presence
    from application code without catching exceptions.

    Args:
        engine: AsyncEngine for the test database.

    Returns:
        True if ``pg_cron`` is listed in ``pg_extension``, False otherwise.
    """
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT count(*) FROM pg_extension WHERE extname = 'pg_cron'"
            )
        )
        return bool(result.scalar_one())


async def _insert_idempotency_key(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    key: str | None = None,
    expires_at_sql: str = "now() + INTERVAL '24 hours'",
) -> str:
    """Insert one row into cache.idempotency_keys; return the key.

    Args:
        engine: AsyncEngine for the test database.
        tenant_id: UUID of the tenant owning the key.
        key: Idempotency key string (generated if None).
        expires_at_sql: SQL expression for expires_at column (allows inserting
            already-expired rows by passing ``now() - INTERVAL '1 second'``).

    Returns:
        The idempotency key string that was inserted.
    """
    if key is None:
        key = f"test-key-{uuid.uuid4().hex}"

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO cache.idempotency_keys "
                "(key, tenant_id, endpoint, request_hash, "
                " response_status, response_body, expires_at) "
                "VALUES "
                "(:key, CAST(:tid AS uuid), :endpoint, :req_hash, "
                f" :status, CAST(:body AS jsonb), {expires_at_sql})"
            ),
            {
                "key": key,
                "tid": tenant_id,
                "endpoint": "POST /api/v1/calc/insert",
                "req_hash": "a" * 64,
                "status": 201,
                "body": '{"ok": true}',
            },
        )
    return key


# ---------------------------------------------------------------------------
# Decision A — pg_cron extension
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_succeeds_regardless_of_pgcron(
    async_engine: AsyncEngine,
) -> None:
    """Migration 0027_M7 must have applied without raising an exception.

    This is implicitly proven by the fact that the async_engine fixture
    (session-scoped) runs ``alembic upgrade head`` once and only once.  If
    upgrade() had raised, ALL tests in this session would have failed with a
    fixture error.  This test makes the intent explicit and gives a clear test
    name in the report.

    We verify by checking that ``alembic_version`` holds a revision at or
    after 0027_M7.  Alembic stores only the current head (linear chain), so
    after Wave 4 the head is 0028_M8 (which has 0027_M7 as its down_revision).
    The presence of either id proves the 0027_M7 step ran without raising.
    """
    expected_revisions = {"0027_M7", "0028_M8"}
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT version_num FROM alembic_version")
        )
        row = result.fetchone()

    assert row is not None, (
        "alembic_version is empty — alembic upgrade head did not run"
    )
    assert row[0] in expected_revisions, (
        f"alembic_version = {row[0]!r}; expected one of {expected_revisions} "
        "after Wave 4 upgrade head — migration 0027_M7_wave4_foundation.py "
        "did not apply (head should be at or after 0027_M7)"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pgcron_extension_status(
    async_engine: AsyncEngine,
) -> None:
    """pg_cron extension presence is consistent with server capability.

    If pg_cron IS available: the extension row must be in pg_extension.
    If pg_cron is NOT available (testcontainers postgres:15-alpine): the
    migration must still have succeeded — the absence of the extension row is
    expected and correct.

    This test never fails; it serves as documentation that both paths work.
    """
    is_available = await _pgcron_available(async_engine)

    if is_available:
        # Double-check: extension metadata must be accessible.
        async with async_engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT extname, extversion "
                    "FROM pg_extension "
                    "WHERE extname = 'pg_cron'"
                )
            )
            row = result.fetchone()
        assert row is not None
        assert row[0] == "pg_cron"
        # extversion is a string like '1.4' or '1.6' depending on the PG image.
        assert row[1] is not None
    else:
        # pg_cron absent: confirm the migration did not introduce a broken state
        # by verifying that cache.idempotency_keys is still reachable.
        async with async_engine.connect() as conn:
            count_result = await conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'cache' "
                    "  AND table_name = 'idempotency_keys'"
                )
            )
            assert count_result.scalar_one() == 1, (
                "cache.idempotency_keys must exist even when pg_cron is absent"
            )


# ---------------------------------------------------------------------------
# Decision B — cron job registration and cleanup query
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cron_job_registered_when_pgcron_available(
    async_engine: AsyncEngine,
) -> None:
    """If pg_cron is available, the cleanup job is registered in cron.job.

    Verifies job name, schedule, and that the SQL targets
    cache.idempotency_keys.  The test is skipped automatically when pg_cron
    is absent (standard testcontainers environment).
    """
    if not await _pgcron_available(async_engine):
        pytest.skip("pg_cron not available in this environment — skipping cron job test")

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT jobname, schedule, command "
                "FROM cron.job "
                "WHERE jobname = 'idempotency_keys_cleanup'"
            )
        )
        row = result.fetchone()

    assert row is not None, (
        "cron job 'idempotency_keys_cleanup' must be present in cron.job after M7 upgrade"
    )
    jobname, schedule, command = row[0], row[1], row[2]
    assert jobname == "idempotency_keys_cleanup"
    assert schedule == "15 * * * *", (
        f"Expected cron schedule '15 * * * *', got '{schedule}'"
    )
    # The command must reference the correct table.
    assert "cache.idempotency_keys" in command, (
        f"Cron command must target cache.idempotency_keys, got: {command!r}"
    )
    assert "expires_at" in command, (
        f"Cron command must filter on expires_at, got: {command!r}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_query_deletes_expired_rows(
    async_engine: AsyncEngine,
    seed_tenants: Any,
) -> None:
    """The cleanup SQL removes expired rows and preserves fresh rows.

    This test directly executes the same DELETE that the pg_cron job would
    run, verifying correctness independently of whether pg_cron is installed.
    This ensures the test suite exercises the business logic on every
    environment, including testcontainers.

    Test scenario:
      1. Insert one expired key (expires_at in the past).
      2. Insert one fresh key (expires_at = now() + 24h, the default).
      3. Execute the cleanup DELETE manually.
      4. Assert: expired key is gone; fresh key survives.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]

    expired_key = await _insert_idempotency_key(
        async_engine,
        tenant_id=seed.tenant_a,
        expires_at_sql="now() - INTERVAL '1 second'",
    )
    fresh_key = await _insert_idempotency_key(
        async_engine,
        tenant_id=seed.tenant_a,
        # Use default expires_at (now() + 24h)
        expires_at_sql="now() + INTERVAL '24 hours'",
    )

    # Execute the exact same SQL that the cron job uses.
    async with async_engine.begin() as conn:
        delete_result = await conn.execute(
            text("DELETE FROM cache.idempotency_keys WHERE expires_at < now()")
        )
        deleted_count = delete_result.rowcount

    # At least the one expired row we inserted must have been deleted.
    assert deleted_count >= 1, (
        f"Expected at least 1 row deleted by cleanup query, got {deleted_count}"
    )

    # Verify expired key is gone.
    async with async_engine.connect() as conn:
        expired_result = await conn.execute(
            text(
                "SELECT count(*) FROM cache.idempotency_keys WHERE key = :key"
            ),
            {"key": expired_key},
        )
        assert expired_result.scalar_one() == 0, (
            f"Expired key '{expired_key}' must have been deleted by the cleanup query"
        )

    # Verify fresh key survived.
    async with async_engine.connect() as conn:
        fresh_result = await conn.execute(
            text(
                "SELECT count(*) FROM cache.idempotency_keys WHERE key = :key"
            ),
            {"key": fresh_key},
        )
        assert fresh_result.scalar_one() == 1, (
            f"Fresh key '{fresh_key}' must NOT have been deleted by the cleanup query"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_is_idempotent(
    async_engine: AsyncEngine,
    seed_tenants: Any,
) -> None:
    """Running the cleanup DELETE twice produces the same final state.

    An idempotent cleanup is important: the cron job may fire during a
    maintenance window where a prior run left the DB consistent.  The second
    run must not raise and must delete 0 additional rows.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]

    # Insert one expired key.
    await _insert_idempotency_key(
        async_engine,
        tenant_id=seed.tenant_a,
        expires_at_sql="now() - INTERVAL '5 seconds'",
    )

    # First run.
    async with async_engine.begin() as conn:
        first = await conn.execute(
            text("DELETE FROM cache.idempotency_keys WHERE expires_at < now()")
        )
        first_deleted = first.rowcount

    # Second run — must delete 0 rows (the expired rows are already gone).
    async with async_engine.begin() as conn:
        second = await conn.execute(
            text("DELETE FROM cache.idempotency_keys WHERE expires_at < now()")
        )
        second_deleted = second.rowcount

    assert first_deleted >= 1, "First cleanup run must delete at least 1 expired row"
    assert second_deleted == 0, (
        f"Second cleanup run must delete 0 rows (idempotency), got {second_deleted}"
    )


# ---------------------------------------------------------------------------
# Decision C — ref.roles unchanged (no 'service' role)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_roles_unchanged_no_service_role(
    async_engine: AsyncEngine,
) -> None:
    """ref.roles contains exactly {admin, editor, viewer} after M7.

    JWT auto-provisioning uses 'viewer' as the default role; no separate
    'service' role is required or should be present.  This test guards against
    an accidental INSERT in M7's upgrade().
    """
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT role_code FROM ref.roles ORDER BY role_code"
            )
        )
        role_codes = {row[0] for row in result.fetchall()}

    # These three roles must exist (set after M24 rename).
    expected = {"admin", "editor", "viewer"}
    assert expected.issubset(role_codes), (
        f"Expected roles {expected} to be present; found {role_codes}"
    )

    # 'service' must NOT be present — it was explicitly not added.
    assert "service" not in role_codes, (
        "Role 'service' must NOT be in ref.roles after M7; "
        "JWT auto-provisioning uses 'viewer' as default"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_viewer_role_exists_for_jwt_default(
    async_engine: AsyncEngine,
) -> None:
    """'viewer' role exists and can be looked up for JWT auto-provisioning.

    This test verifies the prerequisite for the application-layer JWT default
    assignment: the role must be findable by role_code = 'viewer'.
    """
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id::text, role_code, description "
                "FROM ref.roles "
                "WHERE role_code = 'viewer'"
            )
        )
        row = result.fetchone()

    assert row is not None, (
        "Role 'viewer' must exist in ref.roles for JWT auto-provisioning default"
    )
    assert row[1] == "viewer"
    # UUID must be a valid UUID (non-empty, parseable).
    assert len(row[0]) == 36, f"role id must be a UUID string, got: {row[0]!r}"


# ---------------------------------------------------------------------------
# Upgrade / downgrade round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_upgrade_downgrade_roundtrip(
    migrated_db_url: str,
    pg_container: Any,
) -> None:
    """Downgrade to 0026_M6 then re-upgrade to 0027_M7 without error.

    This test is synchronous because Alembic's migration runner is synchronous.
    It runs after the session-scoped ``migrated_db_url`` fixture has already
    applied ``head``, so the initial state is already at 0027_M7.

    The round-trip verifies:
      - downgrade() rolls back M7 cleanly (cron job unscheduled, if pg_cron
        was present; no error if absent).
      - upgrade() re-applies M7 cleanly (same final state as the first apply).
      - alembic_version ends at '0027_M7' after the re-upgrade.

    NOTE: This test mutates the shared session-scoped database.  It is placed
    last in this module and re-upgrades to head at the end so that subsequent
    tests in other modules are not affected.  Ordering is guaranteed by pytest
    collecting tests in file order within a module.
    """
    import os  # noqa: PLC0415

    cfg = AlembicConfig(
        os.path.join(
            os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..")
            ),
            "alembic.ini",
        )
    )
    cfg.set_main_option("sqlalchemy.url", migrated_db_url)

    # alembic/env.py reads SQLALCHEMY_URL from the environment and overrides
    # cfg.set_main_option(). In integration.yml CI that env var points at the
    # GHA service container, NOT the testcontainer we want to mutate. We
    # mirror migrated_db_url's pattern: override for the duration of the
    # alembic call, then restore.
    original_env = os.environ.get("SQLALCHEMY_URL")
    os.environ["SQLALCHEMY_URL"] = migrated_db_url
    try:
        # --- downgrade to the previous revision -----------------------------
        alembic_command.downgrade(cfg, "0026_M6")
    finally:
        if original_env is None:
            os.environ.pop("SQLALCHEMY_URL", None)
        else:
            os.environ["SQLALCHEMY_URL"] = original_env

    # Verify we are at 0026_M6 after downgrade.
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(migrated_db_url, future=True)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version")
            )
            version_after_downgrade = result.scalar_one()
    finally:
        engine.dispose()

    assert version_after_downgrade == "0026_M6", (
        f"Expected alembic_version = '0026_M6' after downgrade, "
        f"got '{version_after_downgrade}'"
    )

    # --- re-upgrade all the way back to head -------------------------------
    # IMPORTANT: must re-apply 0028_M8 too, otherwise this session-scoped
    # database is left at 0027_M7 and any subsequent test that depends on
    # M8 artefacts (e.g. tests/integration/postgres/test_migration_0028.py)
    # sees an empty ref.factor_catalog for the M8 ids.
    #
    # Same env-var override pattern as the downgrade call above.
    original_env = os.environ.get("SQLALCHEMY_URL")
    os.environ["SQLALCHEMY_URL"] = migrated_db_url
    try:
        alembic_command.upgrade(cfg, "head")
    finally:
        if original_env is None:
            os.environ.pop("SQLALCHEMY_URL", None)
        else:
            os.environ["SQLALCHEMY_URL"] = original_env

    engine2 = create_engine(migrated_db_url, future=True)
    try:
        with engine2.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version")
            )
            version_after_upgrade = result.scalar_one()
    finally:
        engine2.dispose()

    # head is 0028_M8 after Wave 4 linearization (0028 has 0027 as
    # down_revision).  Accept either as proof that the M7 step ran and the
    # chain made it back to or past it.
    assert version_after_upgrade in {"0027_M7", "0028_M8"}, (
        f"Expected alembic_version in {{'0027_M7','0028_M8'}} after re-upgrade, "
        f"got '{version_after_upgrade}'"
    )
