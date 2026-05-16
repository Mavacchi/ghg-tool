"""Async SQLAlchemy engine + session factory for GHG Tool.

Session GUC injection:
  On each connection the factory sets ``app.tenant_id``, ``app.role_code``
  (and optionally ``app.user_id``) via ``SET LOCAL`` so that PostgreSQL RLS
  policies (M4) evaluate correctly.  The values come from the decoded JWT
  claims injected by the FastAPI dependency (wave 2 wiring via
  ``api/dependencies/auth.py``).

  Wave 1 note: the ``set_session_gucs`` helper is implemented here and
  called from ``get_db_session`` once the JWT auth dependency exists.
  In wave 1 it is callable directly by tests with explicit arguments.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def _resolve_database_url() -> str:
    """Resolve the async SQLAlchemy URL with fail-closed defaults.

    SEC-P0: no hardcoded ``ghg_app:changeme`` fallback (the previous default
    leaked a known weak password into images / coredumps).  When the env var
    is missing we either:

    - fall back to a clearly-marked test-only DSN when running under pytest
      (``PYTEST_CURRENT_TEST`` is set automatically by the runner so this
      branch is only ever active in CI/local tests), or
    - raise ``RuntimeError`` so the API fails at import time instead of
      silently connecting somewhere unexpected.
    """
    url = os.environ.get("SQLALCHEMY_URL", "").strip()
    if url:
        return url
    if os.environ.get("PYTEST_CURRENT_TEST"):
        # Test-only fallback — never reached outside pytest.
        return "postgresql+asyncpg://ghg_app:test-only@localhost:5432/ghg_tool"
    raise RuntimeError(
        "SQLALCHEMY_URL is required (no insecure default); "
        "set it in the process environment before importing this module."
    )


_DATABASE_URL = _resolve_database_url()

engine = create_async_engine(
    _DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def set_session_gucs(
    session: AsyncSession,
    *,
    tenant_id: str,
    role_code: str,
    user_id: str | None = None,
) -> None:
    """Inject RLS session GUCs into the current transaction.

    Must be called immediately after beginning a transaction, before any
    SQL that touches tenant-scoped tables.  Uses ``SET LOCAL`` so the GUCs
    are transaction-scoped (auto-reset on commit/rollback).

    Args:
        session: The active async SQLAlchemy session.
        tenant_id: UUID string of the authenticated tenant.
        role_code: One of 'editor', 'admin', 'viewer'.
        user_id: UUID string of the authenticated user (optional; used by audit log).
    """
    await session.execute(
        # Use text() to ensure parameterised binding for string values
        __import__("sqlalchemy").text(
            "SELECT set_config('app.tenant_id', :tid, true), "
            "       set_config('app.role_code', :role, true)"
        ),
        {"tid": tenant_id, "role": role_code},
    )
    if user_id is not None:
        await session.execute(
            __import__("sqlalchemy").text(
                "SELECT set_config('app.user_id', :uid, true)"
            ),
            {"uid": user_id},
        )


async def get_db_session(
    # Wave 2: inject jwt_claims: dict[str, Any] from Depends(verify_jwt)
    jwt_claims: dict[str, Any] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session with GUCs pre-set.

    Wave 1: if ``jwt_claims`` is None (e.g. in ETL / test contexts), GUCs
    are not injected — caller must call ``set_session_gucs`` manually.

    Args:
        jwt_claims: Decoded JWT payload from the FastAPI auth dependency
                    (wave 2 wiring).  Expected keys: ``tenant_id``, ``role``,
                    ``sub`` (user UUID).

    Yields:
        An ``AsyncSession`` with RLS GUCs set for the request lifetime.
    """
    async with AsyncSessionFactory() as session, session.begin():
        if jwt_claims is not None:
            await set_session_gucs(
                session,
                tenant_id=jwt_claims["tenant_id"],
                role_code=jwt_claims["role"],
                user_id=jwt_claims.get("sub"),
            )
        yield session
