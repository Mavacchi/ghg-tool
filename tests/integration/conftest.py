"""Integration test fixtures for tests/integration/**.

These tests REQUIRE a live PostgreSQL (locally via docker-compose.test.yml
on port 5433, or in CI via integration.yml service container on 5432).
The connection string is read from SQLALCHEMY_ASYNC_URL (CI) or
DATABASE_URL (local).

RLS note (M4): every tenant-scoped table has FORCE ROW LEVEL SECURITY.
The test session uses a superuser connection (ghg_test is the DB owner
created by the CI service container), which bypasses RLS by default.
For tests that explicitly verify RLS enforcement, the fixture sets the
session GUCs ``app.tenant_id`` and ``app.role_code`` via set_config so
that policies evaluate correctly within the transaction.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Connection URL — prefer CI env vars; fall back to local docker-compose stack
# ---------------------------------------------------------------------------
_ASYNC_URL = (
    os.getenv("SQLALCHEMY_ASYNC_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql+asyncpg://ghg_test:ghg_test_password@localhost:5433/ghg_tool_test"
)

# ---------------------------------------------------------------------------
# Session-scoped engine (one pool shared by all integration tests in a run)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Yield a session-scoped async engine; dispose on teardown."""
    engine = create_async_engine(_ASYNC_URL, echo=False, future=True)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Per-test transaction fixture — rolls back after every test
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession whose transaction is rolled back after the test.

    The ``session.begin()`` context manager auto-rolls-back if no explicit
    commit is issued.  This keeps each test's changes invisible to others
    and to the persistent database.
    """
    SessionLocal = async_sessionmaker(
        db_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with SessionLocal() as session, session.begin():
        yield session
        # Context manager exits without commit → automatic rollback


# ---------------------------------------------------------------------------
# Tenant ID fixture — session-scoped UUID shared across all integration tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def tenant_id(db_engine: AsyncEngine) -> str:
    """Return the UUID of the seeded 'CERAMIC_TILE_CO' tenant.

    Reads from the live database (seeded in M0) rather than generating a new
    UUID, so that REFERENCES ref.tenants(id) constraints are satisfied without
    needing a test-only INSERT.
    """
    SessionLocal = async_sessionmaker(
        db_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT id::text FROM ref.tenants WHERE code = 'CERAMIC_TILE_CO' LIMIT 1")
        )
        row = result.fetchone()
        if row is None:
            raise RuntimeError(
                "Seeded tenant 'CERAMIC_TILE_CO' not found — "
                "ensure alembic upgrade head has been run before the integration suite."
            )
        return str(row[0])


# ---------------------------------------------------------------------------
# Fixture: seed factor id — the one deterministic factor from M2
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def stoich_factor_id(db_engine: AsyncEngine, tenant_id: str) -> str:
    """Return the UUID of STOICH_CACO3_IPCC_2006 from ref.factor_catalog.

    This is the only factor in M2 with a non-NULL, non-TBC value (0.4397).
    Using it as the FK for test emissions avoids needing to insert a factor.
    """
    SessionLocal = async_sessionmaker(
        db_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id::text FROM ref.factor_catalog "
                "WHERE factor_id = 'STOICH_CACO3_IPCC_2006' "
                "  AND tenant_id = :tid "
                "LIMIT 1"
            ),
            {"tid": tenant_id},
        )
        row = result.fetchone()
        if row is None:
            raise RuntimeError(
                "STOICH_CACO3_IPCC_2006 factor not found — "
                "ensure alembic upgrade head (M2) has been run."
            )
        return str(row[0])


# ---------------------------------------------------------------------------
# Helper fixture: set RLS session GUCs within the test transaction
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def rls_session(
    db_session: AsyncSession,
    tenant_id: str,
) -> AsyncSession:
    """Yield the db_session with RLS GUCs set for data_steward role.

    Uses ``set_config(..., true)`` (transaction-local) so the GUCs are reset
    automatically when the transaction rolls back.  The superuser connection
    still bypasses FORCE ROW LEVEL SECURITY — these GUCs are consumed by the
    RLS policies when they evaluate ``current_setting(...)``.
    """
    await db_session.execute(
        text(
            "SELECT set_config('app.tenant_id', :tid, true), "
            "       set_config('app.role_code', 'data_steward', true)"
        ),
        {"tid": tenant_id},
    )
    return db_session


# ---------------------------------------------------------------------------
# Helper: assert that a callable raises an immutability-guard PG exception
# ---------------------------------------------------------------------------


def assert_immutability_violation(exc: Exception, *, trigger_hint: str = "") -> None:
    """Assert *exc* is the expected immutability guard exception from M0/M1.

    Accepts both ``IntegrityError`` (raised when SQLAlchemy catches a
    constraint violation) and ``ProgrammingError`` (raised for RAISE EXCEPTION
    in a PL/pgSQL trigger).  The error message must contain 'forbidden' or the
    optional *trigger_hint* substring.

    Args:
        exc: The exception raised by the attempted mutation.
        trigger_hint: Optional substring to search for in the error string
            (e.g. the trigger name or part of the RAISE EXCEPTION message).
    """
    assert isinstance(exc, IntegrityError | ProgrammingError), (
        f"Expected IntegrityError or ProgrammingError, got {type(exc).__name__}: {exc}"
    )
    err_str = str(exc).lower()
    if trigger_hint:
        assert trigger_hint.lower() in err_str, (
            f"Expected '{trigger_hint}' in error string, got: {exc}"
        )
    else:
        assert "forbidden" in err_str or "p0001" in err_str, (
            f"Expected immutability violation message, got: {exc}"
        )
