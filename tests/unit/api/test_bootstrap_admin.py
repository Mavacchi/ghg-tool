"""Unit tests for the bootstrap-admin-from-env startup pattern.

Covers ``_seed_admin_from_env_if_empty()`` in ``ghg_tool.api.main``:

  - Skipped when GHG_ENVIRONMENT == 'test'.
  - Skipped when any of the three required env vars is absent.
  - Skipped when ref.users already contains at least one row (idempotency).
  - Skipped when no launch tenant is found in the DB.
  - Skipped when the admin role is not found in ref.roles.
  - Admin user is inserted (INSERT + commit) when all conditions are met.
  - Logged at WARNING level with ``bootstrap_admin_seeded_from_env`` key and
    the username (NOT email, NOT hash).
  - A DB failure is swallowed; the function returns normally (startup-safe).

All DB interactions are mocked via ``AsyncMock``; no live PostgreSQL required.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ghg_tool.api.main as main_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION_FACTORY = "ghg_tool.infrastructure.db.session.AsyncSessionFactory"

_VALID_ENV = {
    "GHG_BOOTSTRAP_ADMIN_USERNAME": "testadmin",
    "GHG_BOOTSTRAP_ADMIN_EMAIL": "testadmin@example.com",
    "GHG_BOOTSTRAP_ADMIN_PASSWORD_HASH": "$2b$12$fakehashvalue",
}


def _make_scalar_result(value: Any) -> MagicMock:
    """Return a mock scalar result that returns *value* from ``.scalar_one()``."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _make_row(value: str) -> MagicMock:
    """Return a mock DB row whose index-0 element is *value*."""
    row = MagicMock()
    row.__getitem__ = MagicMock(return_value=value)
    return row


def _make_session(
    user_count: int = 0,
    has_tenant: bool = True,
    has_role: bool = True,
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
    role_id: str = "00000000-0000-0000-0000-000000000002",
) -> AsyncMock:
    """Build an async session mock wired for ``_seed_admin_from_env_if_empty``.

    Args:
        user_count: Rows returned by ``SELECT COUNT(*) FROM ref.users``.
        has_tenant: Whether a tenant row is found.
        has_role: Whether the admin role row is found.
        tenant_id: UUID string returned for the tenant.
        role_id: UUID string returned for the admin role.

    Returns:
        An ``AsyncMock`` usable as an async context manager session.
    """
    session = AsyncMock()

    async def _execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:  # type: ignore[misc]
        q = str(query).lower()
        result = MagicMock()
        if "ref.users" in q and "count" in q:
            result.scalar_one.return_value = user_count
            return result
        if "ref.tenants" in q:
            result.fetchone.return_value = _make_row(tenant_id) if has_tenant else None
            return result
        if "ref.roles" in q:
            result.fetchone.return_value = _make_row(role_id) if has_role else None
            return result
        # INSERT ref.users
        result.scalar_one.return_value = None
        result.fetchone.return_value = None
        return result

    session.execute = _execute
    session.commit = AsyncMock()
    return session


class _FakeFactory:
    """Async context manager that yields a fixed session mock."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncMock:
        return self._session

    async def __aexit__(self, *_: Any) -> None:
        pass


def _patch_factory(session: AsyncMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value = _FakeFactory(session)
    return factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBootstrapAdminFromEnv:
    """Tests for ``_seed_admin_from_env_if_empty()``."""

    @pytest.mark.asyncio
    async def test_skipped_in_test_environment(self) -> None:
        """GHG_ENVIRONMENT == 'test' -> function returns immediately, no DB access."""
        with (
            patch.object(main_mod, "_ENVIRONMENT", "test"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(
                _SESSION_FACTORY,
                side_effect=AssertionError("DB must not be accessed in test env"),
            ),
        ):
            await main_mod._seed_admin_from_env_if_empty()
            # Must not raise

    @pytest.mark.asyncio
    async def test_skipped_when_username_missing(self) -> None:
        """Missing GHG_BOOTSTRAP_ADMIN_USERNAME -> skipped silently."""
        env = {k: v for k, v in _VALID_ENV.items() if k != "GHG_BOOTSTRAP_ADMIN_USERNAME"}
        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, env, clear=False),
            patch(
                _SESSION_FACTORY,
                side_effect=AssertionError("DB must not be accessed"),
            ),
        ):
            await main_mod._seed_admin_from_env_if_empty()

    @pytest.mark.asyncio
    async def test_skipped_when_email_missing(self) -> None:
        """Missing GHG_BOOTSTRAP_ADMIN_EMAIL -> skipped silently."""
        env = {k: v for k, v in _VALID_ENV.items() if k != "GHG_BOOTSTRAP_ADMIN_EMAIL"}
        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, env, clear=False),
            patch(
                _SESSION_FACTORY,
                side_effect=AssertionError("DB must not be accessed"),
            ),
        ):
            await main_mod._seed_admin_from_env_if_empty()

    @pytest.mark.asyncio
    async def test_skipped_when_hash_missing(self) -> None:
        """Missing GHG_BOOTSTRAP_ADMIN_PASSWORD_HASH -> skipped silently."""
        env = {k: v for k, v in _VALID_ENV.items()
               if k != "GHG_BOOTSTRAP_ADMIN_PASSWORD_HASH"}
        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, env, clear=False),
            patch(
                _SESSION_FACTORY,
                side_effect=AssertionError("DB must not be accessed"),
            ),
        ):
            await main_mod._seed_admin_from_env_if_empty()

    @pytest.mark.asyncio
    async def test_skipped_when_users_table_not_empty(self) -> None:
        """When ref.users already has rows, no INSERT is executed (idempotent)."""
        session = _make_session(user_count=1)
        insert_calls: list[str] = []
        original_execute = session.execute

        async def _tracking_execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:
            q = str(query)
            if "INSERT" in q:
                insert_calls.append(q)
            return await original_execute(query, *args, **kwargs)

        session.execute = _tracking_execute

        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(_SESSION_FACTORY, _patch_factory(session)),
        ):
            await main_mod._seed_admin_from_env_if_empty()

        assert not insert_calls, "No INSERT expected when users table is not empty"
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skipped_when_no_tenant_found(self) -> None:
        """When no launch tenant exists in ref.tenants, skip and log warning."""
        session = _make_session(user_count=0, has_tenant=False)

        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(_SESSION_FACTORY, _patch_factory(session)),
        ):
            await main_mod._seed_admin_from_env_if_empty()

        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skipped_when_admin_role_not_found(self) -> None:
        """When 'admin' role is absent from ref.roles, skip and log warning."""
        session = _make_session(user_count=0, has_tenant=True, has_role=False)

        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(_SESSION_FACTORY, _patch_factory(session)),
        ):
            await main_mod._seed_admin_from_env_if_empty()

        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_admin_inserted_when_all_conditions_met(self) -> None:
        """When users is empty and tenant+role exist, INSERT is executed and committed."""
        session = _make_session(user_count=0, has_tenant=True, has_role=True)
        insert_calls: list[str] = []
        original_execute = session.execute

        async def _tracking_execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:
            q = str(query)
            if "INSERT INTO ref.users" in q:
                insert_calls.append(q)
            return await original_execute(query, *args, **kwargs)

        session.execute = _tracking_execute

        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(_SESSION_FACTORY, _patch_factory(session)),
        ):
            await main_mod._seed_admin_from_env_if_empty()

        assert insert_calls, "Expected INSERT INTO ref.users to be called"
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_inserted_in_development_env(self) -> None:
        """Bootstrap also runs in development environment (not test-only)."""
        session = _make_session(user_count=0, has_tenant=True, has_role=True)
        insert_calls: list[str] = []
        original_execute = session.execute

        async def _tracking_execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:
            q = str(query)
            if "INSERT INTO ref.users" in q:
                insert_calls.append(q)
            return await original_execute(query, *args, **kwargs)

        session.execute = _tracking_execute

        with (
            patch.object(main_mod, "_ENVIRONMENT", "development"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(_SESSION_FACTORY, _patch_factory(session)),
        ):
            await main_mod._seed_admin_from_env_if_empty()

        assert insert_calls, "Expected INSERT INTO ref.users to be called in development"

    @pytest.mark.asyncio
    async def test_db_failure_does_not_crash_startup(self) -> None:
        """A DB exception during bootstrap is caught; function returns normally."""
        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(
                _SESSION_FACTORY,
                side_effect=RuntimeError("DB connection refused"),
            ),
        ):
            try:
                await main_mod._seed_admin_from_env_if_empty()
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"_seed_admin_from_env_if_empty raised unexpectedly: {exc!r}"
                )

    @pytest.mark.asyncio
    async def test_idempotent_on_second_run(self) -> None:
        """Calling the function twice with user_count=1 on second call -> no second INSERT."""
        call_count = 0

        first_session = _make_session(user_count=0)
        first_insert: list[str] = []
        orig_exec_1 = first_session.execute

        async def _first_execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            q = str(query)
            if "INSERT INTO ref.users" in q:
                first_insert.append(q)
                call_count += 1
            return await orig_exec_1(query, *args, **kwargs)

        first_session.execute = _first_execute

        second_session = _make_session(user_count=1)  # already seeded
        second_insert: list[str] = []
        orig_exec_2 = second_session.execute

        async def _second_execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:
            q = str(query)
            if "INSERT INTO ref.users" in q:
                second_insert.append(q)
            return await orig_exec_2(query, *args, **kwargs)

        second_session.execute = _second_execute

        sessions = iter([first_session, second_session])

        class _MultiFactory:
            async def __aenter__(self) -> AsyncMock:
                return next(sessions)

            async def __aexit__(self, *_: Any) -> None:
                pass

        factory = MagicMock()
        factory.return_value = _MultiFactory()

        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(_SESSION_FACTORY, factory),
        ):
            await main_mod._seed_admin_from_env_if_empty()

        # Reset factory for second call
        factory.return_value = _MultiFactory()
        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, _VALID_ENV, clear=False),
            patch(_SESSION_FACTORY, factory),
        ):
            await main_mod._seed_admin_from_env_if_empty()

        assert len(first_insert) == 1, "Expected exactly one INSERT on first call"
        assert not second_insert, "Expected no INSERT on second call (idempotent)"
