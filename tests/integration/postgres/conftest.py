"""Session-scoped fixtures for the testcontainers-backed PostgreSQL integration suite.

Every fixture in this file targets a real PostgreSQL 15 container spun up by
testcontainers-python.  No external Docker Compose stack or GHA service
container is required: testcontainers pulls the image and manages lifecycle
automatically, both locally and in CI (as long as the Docker daemon is
reachable).

Design choices:
  - `pg_container` is session-scoped: one container per pytest session.
    Starting a container takes ~5 s; reusing it across all tests avoids
    paying that cost for every test file.
  - `migrated_db_url` applies `alembic upgrade head` once per session.
    Tests that need a pristine schema use per-test TRUNCATE (not per-test
    container restarts, which would be prohibitively slow).
  - `async_engine` uses NullPool so connections are never shared across the
    asyncio event loops of different async test functions.
  - Tests that exercise trigger behaviour (which fires on COMMIT) open and
    commit their own connections; tests that only verify state can use the
    rollback-on-exit `db_session` fixture.

Naming conventions:
  - All fixtures that touch the database are async (pytest-asyncio).
  - The `seed_tenants` fixture returns a NamedTuple so callers address tenants
    by name (`seed.tenant_a`, `seed.tenant_b`) rather than by position.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import NamedTuple

import pytest
import pytest_asyncio
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Container and URL constants
# ---------------------------------------------------------------------------

_PG_IMAGE = "postgres:15-alpine"
_PG_USER = "ghg_tc"
_PG_PASSWORD = "ghg_tc_pw"
_PG_DBNAME = "ghg_tc_db"

# alembic.ini lives two directories above this file (repo root).
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_ALEMBIC_INI = os.path.join(_REPO_ROOT, "alembic.ini")

# Non-superuser role used to exercise RLS in tests.  The testcontainer's
# default user is a PostgreSQL SUPERUSER and therefore bypasses every RLS
# policy regardless of ENABLE / FORCE ROW LEVEL SECURITY.  Cross-tenant
# isolation can only be verified end-to-end by switching the active role
# (via SET LOCAL ROLE) to a NOSUPERUSER, NOBYPASSRLS role.  Seed and
# teardown statements remain on the superuser connection so they are not
# blocked by the tenant-isolation policy themselves.
RLS_TEST_ROLE: str = "ghg_test_app"



# ---------------------------------------------------------------------------
# Named tuple for two-tenant seed
# ---------------------------------------------------------------------------


class TenantSeed(NamedTuple):
    """UUIDs for the two seed tenants used in isolation tests."""

    tenant_a: str
    tenant_b: str
    user_a: str
    user_b: str


# ---------------------------------------------------------------------------
# pg_container -- session-scoped; starts the Docker container once per run
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    """Spin up a postgres:15-alpine container; yield it; stop on teardown.

    testcontainers manages port allocation and container lifecycle.
    The container is pinned to postgres:15-alpine so test results are
    deterministic across developer machines and CI runners.
    """
    with PostgresContainer(
        image=_PG_IMAGE,
        username=_PG_USER,
        password=_PG_PASSWORD,
        dbname=_PG_DBNAME,
    ) as container:
        yield container


# ---------------------------------------------------------------------------
# migrated_db_url -- applies alembic upgrade head against the container
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def migrated_db_url(pg_container: PostgresContainer) -> str:
    """Return the psycopg DSN after applying all Alembic migrations.

    Constructs an AlembicConfig programmatically so that `sqlalchemy.url`
    points to the testcontainers instance rather than the default in
    alembic.ini.  This is the canonical way to run migrations against an
    ephemeral test database without patching environment variables.

    Uses the synchronous psycopg driver (postgresql+psycopg) because
    Alembic's `engine_from_config` is synchronous.

    Returns:
        The psycopg-dialect connection string for the migrated container.
    """
    # testcontainers exposes a `get_connection_url()` that uses psycopg2 dialect.
    # We override the dialect prefix to use psycopg (v3) which is the driver
    # already in the project's dependencies.
    raw_url: str = pg_container.get_connection_url()
    # testcontainers builds postgresql+psycopg2://... so replace the driver part.
    sync_url = raw_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    # Also handle plain postgresql:// prefix (older testcontainers versions)
    if sync_url.startswith("postgresql://"):
        sync_url = "postgresql+psycopg://" + sync_url[len("postgresql://"):]

    # alembic/env.py reads $SQLALCHEMY_URL and overrides any programmatic
    # `cfg.set_main_option("sqlalchemy.url", ...)`. In the integration.yml CI
    # job that env var points at the GHA service container (a DIFFERENT
    # database than the testcontainer we just started), so migrations get
    # applied there and our fixture queries hit an un-migrated DB.
    # Override the env var for the duration of the alembic call.
    original_env = os.environ.get("SQLALCHEMY_URL")
    os.environ["SQLALCHEMY_URL"] = sync_url
    try:
        cfg = AlembicConfig(_ALEMBIC_INI)
        cfg.set_main_option("sqlalchemy.url", sync_url)
        alembic_command.upgrade(cfg, "head")
    finally:
        if original_env is None:
            os.environ.pop("SQLALCHEMY_URL", None)
        else:
            os.environ["SQLALCHEMY_URL"] = original_env

    # Provision the non-superuser test role used to exercise RLS.  Done here
    # (after `alembic upgrade head`) so the role has GRANTs on every object
    # introduced by the latest migration.
    _provision_rls_test_role(sync_url, _PG_PASSWORD)

    return sync_url


def _provision_rls_test_role(sync_url: str, password: str) -> None:
    """Create (or refresh grants for) ``RLS_TEST_ROLE`` on the test database.

    The testcontainer's default user is a SUPERUSER, which BYPASSES every
    RLS policy regardless of FORCE ROW LEVEL SECURITY.  The 3 cross-tenant
    isolation tests in ``test_rls_tenant_isolation.py`` therefore *must*
    execute their tenant-scoped queries under a NOSUPERUSER, NOBYPASSRLS
    role.  We create that role idempotently here and grant it the minimal
    privileges required to INSERT into and SELECT from the tables touched
    by the RLS suite (``calc.emissions_consolidated``,
    ``ops.chart_annotations``, plus the FK targets they reference).

    Tests opt into this role on a per-transaction basis via
    ``SET LOCAL ROLE ghg_test_app`` inside ``_set_gucs``.  Seed and teardown
    code keeps running as the superuser owner so it is not blocked by the
    very policy under test.

    This is an *integration-test* fix, not a production migration: in
    real deployments the application connects as ``ghg_app`` (NOSUPERUSER)
    by configuration, not by DDL.

    Args:
        sync_url: ``postgresql+psycopg://...`` DSN for the migrated DB.
        password: Password to assign to the test role (matches the
            container password so dual-role connections share creds).
    """
    from sqlalchemy import create_engine  # noqa: PLC0415

    role = RLS_TEST_ROLE
    # ``password`` is accepted for symmetry with the application bootstrap
    # but unused: the test role is reached via ``SET ROLE``, not LOGIN, so
    # no password is required.  Kept in the signature to make the contract
    # explicit for a future move to a separate LOGIN connection.
    del password
    engine = create_engine(sync_url, future=True)
    try:
        with engine.begin() as conn:
            # Idempotent CREATE ROLE.  NOSUPERUSER + NOBYPASSRLS are the two
            # attributes that *force* RLS to be evaluated for this role; the
            # other flags are defensive defaults.  No LOGIN: tests reach the
            # role via ``SET LOCAL ROLE`` on an existing superuser connection.
            conn.execute(
                text(
                    "DO $$ BEGIN "
                    f"  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                    f"  THEN CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS "
                    "       NOLOGIN NOINHERIT; "
                    "  END IF; "
                    "END $$;"
                )
            )
            # Re-issue grants every session: cheap and idempotent.  Schema-wide
            # grants are intentionally broad because this role is only ever
            # used inside RLS tests, and the policies are exactly what we're
            # validating; narrowing privileges further would not strengthen
            # the test.
            for schema in ("ref", "raw", "calc", "ops", "auth"):
                conn.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {role};"))
                conn.execute(
                    text(
                        f"GRANT SELECT, INSERT, UPDATE, DELETE "
                        f"ON ALL TABLES IN SCHEMA {schema} TO {role};"
                    )
                )
                conn.execute(
                    text(
                        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} "
                        f"TO {role};"
                    )
                )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# async_engine -- asyncpg-based engine bound to the migrated DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def async_engine(migrated_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Yield a session-scoped AsyncEngine using the asyncpg driver.

    Converts the psycopg DSN to asyncpg by replacing the driver prefix.
    NullPool prevents cross-loop connection sharing (see design notes above).

    Yields:
        An AsyncEngine connected to the migrated container database.
    """
    asyncpg_url = migrated_db_url.replace(
        "postgresql+psycopg://", "postgresql+asyncpg://", 1
    )
    engine = create_async_engine(asyncpg_url, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# async_session_factory -- sessionmaker bound to the async engine
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def async_session_factory(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Return an async_sessionmaker bound to the migrated engine.

    expire_on_commit=False prevents SQLAlchemy from expiring ORM objects
    after commit, which would trigger additional lazy-load queries and
    confuse tests that check attribute values immediately after commit.

    Returns:
        Configured async_sessionmaker.
    """
    return async_sessionmaker(async_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# db_session -- per-test async session that rolls back after each test
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def db_session(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession that rolls back after each test.

    The rollback pattern gives each test a clean slate without truncating
    tables or restarting the container.  GUCs set inside the transaction
    (via SET LOCAL / set_config(..., true)) are automatically discarded by
    the rollback.

    Note: tests that must COMMIT (e.g. trigger tests that only fire on
    real commits) should NOT use this fixture; they must manage their own
    connection via `async_engine` and TRUNCATE tables in teardown.

    Yields:
        An AsyncSession within an open-but-not-yet-committed transaction.
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


# ---------------------------------------------------------------------------
# seed_tenants -- inserts two tenants + one user each; session-scoped
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def seed_tenants(
    async_engine: AsyncEngine,
) -> TenantSeed:
    """Insert two test tenants (A, B) and one esg_manager user per tenant.

    This fixture is session-scoped because tenant rows are referenced by FK
    in every subsequent test.  The rows are committed (not rolled back) so
    that they survive for the full session.

    The inserted tenants use UUID-based codes so they do not collide with
    the 'CERAMIC_TILE_CO' tenant seeded by M0.

    Returns:
        TenantSeed(tenant_a, tenant_b, user_a, user_b) -- UUID strings.
    """
    tenant_a_id = str(uuid.uuid4())
    tenant_b_id = str(uuid.uuid4())
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    code_a = f"TC_A_{tenant_a_id[:8].upper()}"
    code_b = f"TC_B_{tenant_b_id[:8].upper()}"

    async with async_engine.begin() as conn:
        # Look up the admin role id once (role was renamed from esg_manager in M24)
        role_row = await conn.execute(
            text("SELECT id::text FROM ref.roles WHERE role_code = 'admin' LIMIT 1")
        )
        role_id = role_row.scalar_one()

        # Insert tenant A
        await conn.execute(
            text(
                "INSERT INTO ref.tenants (id, code, legal_name) "
                "VALUES (CAST(:id AS uuid), :code, :name)"
            ),
            {"id": tenant_a_id, "code": code_a, "name": "Test Tenant A"},
        )
        # Insert tenant B
        await conn.execute(
            text(
                "INSERT INTO ref.tenants (id, code, legal_name) "
                "VALUES (CAST(:id AS uuid), :code, :name)"
            ),
            {"id": tenant_b_id, "code": code_b, "name": "Test Tenant B"},
        )
        # Insert user A (esg_manager for tenant A)
        await conn.execute(
            text(
                "INSERT INTO ref.users "
                "(id, tenant_id, username, email, password_hash, role_id) "
                "VALUES ("
                "  CAST(:uid AS uuid), CAST(:tid AS uuid), "
                "  :uname, :email, :phash, CAST(:role AS uuid)"
                ")"
            ),
            {
                "uid": user_a_id,
                "tid": tenant_a_id,
                "uname": f"user_a_{user_a_id[:8]}",
                "email": f"user_a_{user_a_id[:8]}@example.test",
                "phash": "$2b$12$placeholder_hash_a",
                "role": role_id,
            },
        )
        # Insert user B (esg_manager for tenant B)
        await conn.execute(
            text(
                "INSERT INTO ref.users "
                "(id, tenant_id, username, email, password_hash, role_id) "
                "VALUES ("
                "  CAST(:uid AS uuid), CAST(:tid AS uuid), "
                "  :uname, :email, :phash, CAST(:role AS uuid)"
                ")"
            ),
            {
                "uid": user_b_id,
                "tid": tenant_b_id,
                "uname": f"user_b_{user_b_id[:8]}",
                "email": f"user_b_{user_b_id[:8]}@example.test",
                "phash": "$2b$12$placeholder_hash_b",
                "role": role_id,
            },
        )

    return TenantSeed(
        tenant_a=tenant_a_id,
        tenant_b=tenant_b_id,
        user_a=user_a_id,
        user_b=user_b_id,
    )


# ---------------------------------------------------------------------------
# stoich_factor_for_tenant -- inserts a minimal published factor for a given tenant
# ---------------------------------------------------------------------------


async def insert_factor_for_tenant(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    is_published: bool = True,
) -> str:
    """Insert a minimal ref.factor_catalog row for tenant_id; return its UUID.

    Used by test helpers that need a valid factor_id FK when inserting
    emission rows for a specific tenant.

    Args:
        engine: AsyncEngine for the test database.
        tenant_id: UUID string of the target tenant.
        is_published: Whether the factor row is published (default True).

    Returns:
        UUID string of the inserted factor row.
    """
    factor_row_id = str(uuid.uuid4())
    factor_id_code = f"TEST_FACTOR_{factor_row_id[:8].upper()}"
    async with engine.begin() as conn:
        if is_published:
            await conn.execute(
                text(
                    "INSERT INTO ref.factor_catalog ("
                    "  id, tenant_id, factor_id, version, substance, scope, "
                    "  category, source, value, unit, gwp_set, valid_from, "
                    "  is_published, published_at, published_by"
                    ") VALUES ("
                    "  CAST(:id AS uuid), CAST(:tid AS uuid), :fid, '2006', "
                    "  'CO2', 1, 'combustion', 'IPCC', 0.5, 'kg/kWh', 'AR6', "
                    "  '2024-01-01', TRUE, now(), 'test_runner'"
                    ")"
                ),
                {"id": factor_row_id, "tid": tenant_id, "fid": factor_id_code},
            )
        else:
            await conn.execute(
                text(
                    "INSERT INTO ref.factor_catalog ("
                    "  id, tenant_id, factor_id, version, substance, scope, "
                    "  category, source, value, unit, gwp_set, valid_from, "
                    "  is_published"
                    ") VALUES ("
                    "  CAST(:id AS uuid), CAST(:tid AS uuid), :fid, '2006', "
                    "  'CO2', 1, 'combustion', 'IPCC', 0.5, 'kg/kWh', 'AR6', "
                    "  '2024-01-01', FALSE"
                    ")"
                ),
                {"id": factor_row_id, "tid": tenant_id, "fid": factor_id_code},
            )
    return factor_row_id
