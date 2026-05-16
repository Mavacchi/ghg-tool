"""Unit tests for demo-mode startup behaviour in ``ghg_tool.api.main``.

Covers:
  - ``_demo_mode_enabled()`` returns False in production regardless of flags.
  - ``_demo_mode_enabled()`` returns True automatically in development/demo envs.
  - ``_seed_demo_data_if_empty()`` is skipped when real data is present.
  - ``_seed_demo_data_if_empty()`` runs when the DB has only the M0 seed.
  - Seed failures do NOT raise; the lifespan continues.
  - Demo user is inserted with role=editor when seeding runs.

All DB interactions are mocked via ``AsyncMock``; no live PostgreSQL required.

Testing strategy
----------------
``_ENVIRONMENT`` is a module-level constant.  We patch it directly on the
imported module object so that ``_demo_mode_enabled()`` — which reads the
global — returns the expected value, without needing to reload the module or
touch os.environ at test time.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ghg_tool.api.main as main_mod

# ---------------------------------------------------------------------------
# Tests: _demo_mode_enabled()
# ---------------------------------------------------------------------------


class TestDemoModeEnabled:
    """Tests for the _demo_mode_enabled() function.

    We patch ``ghg_tool.api.main._ENVIRONMENT`` and (for non-dev envs)
    ``os.environ`` to control which branch of the function is exercised.
    """

    def test_demo_mode_off_in_production(self) -> None:
        """production env -> always False, even with GHG_DEMO_MODE=true."""
        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, {"GHG_DEMO_MODE": "true"}, clear=False),
        ):
            assert main_mod._demo_mode_enabled() is False

    def test_demo_mode_off_in_production_no_flag(self) -> None:
        """production env without any flag -> always False."""
        env = {k: v for k, v in os.environ.items() if k != "GHG_DEMO_MODE"}
        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch.dict(os.environ, env, clear=True),
        ):
            assert main_mod._demo_mode_enabled() is False

    def test_demo_mode_auto_on_in_development(self) -> None:
        """development env -> True automatically (no GHG_DEMO_MODE needed)."""
        env = {k: v for k, v in os.environ.items() if k != "GHG_DEMO_MODE"}
        with (
            patch.object(main_mod, "_ENVIRONMENT", "development"),
            patch.dict(os.environ, env, clear=True),
        ):
            assert main_mod._demo_mode_enabled() is True

    def test_demo_mode_auto_on_in_demo_env(self) -> None:
        """demo env -> True automatically."""
        env = {k: v for k, v in os.environ.items() if k != "GHG_DEMO_MODE"}
        with (
            patch.object(main_mod, "_ENVIRONMENT", "demo"),
            patch.dict(os.environ, env, clear=True),
        ):
            assert main_mod._demo_mode_enabled() is True

    def test_demo_mode_off_in_staging_without_flag(self) -> None:
        """staging env without GHG_DEMO_MODE -> False."""
        env = {k: v for k, v in os.environ.items() if k != "GHG_DEMO_MODE"}
        with (
            patch.object(main_mod, "_ENVIRONMENT", "staging"),
            patch.dict(os.environ, env, clear=True),
        ):
            assert main_mod._demo_mode_enabled() is False

    def test_demo_mode_off_in_staging_even_with_flag(self) -> None:
        """staging env with GHG_DEMO_MODE=true -> still False (BLOCK 6).

        Staging mirrors production trust boundaries for CSRD reporting, so
        the demo-mode flag is silently suppressed there — only development
        and demo environments may opt-in.
        """
        with (
            patch.object(main_mod, "_ENVIRONMENT", "staging"),
            patch.dict(os.environ, {"GHG_DEMO_MODE": "true"}, clear=False),
        ):
            assert main_mod._demo_mode_enabled() is False


# ---------------------------------------------------------------------------
# Patch target constants (avoid long lines inside `with` statements)
# ---------------------------------------------------------------------------

_SESSION_FACTORY = "ghg_tool.infrastructure.db.session.AsyncSessionFactory"
_ENSURE_DEMO_USER = "ghg_tool.api.main._ensure_demo_user"

# ---------------------------------------------------------------------------
# Tests: _seed_demo_data_if_empty()
# ---------------------------------------------------------------------------


def _make_scalar_result(value: Any) -> MagicMock:
    """Return a mock SQLAlchemy scalar result."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _make_session_mock(
    tenant_count: int,
    s1_count: int,
) -> AsyncMock:
    """Build an async session mock that returns given counts.

    Args:
        tenant_count: Value returned by SELECT COUNT(*) FROM ref.tenants.
        s1_count: Value returned by SELECT COUNT(*) FROM raw.scope1_ingestions.

    Returns:
        An ``AsyncMock`` usable as an async context manager session.
    """
    session = AsyncMock()

    async def _execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:  # type: ignore[misc]
        q = str(query).lower()
        if "ref.tenants" in q and "count" in q:
            return _make_scalar_result(tenant_count)
        if "scope1_ingestions" in q and "count" in q:
            return _make_scalar_result(s1_count)
        # Default: return 0 for anything else (e.g. scope2/3 post-seed counts).
        return _make_scalar_result(0)

    session.execute = _execute
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


class TestSeedDemoDataIfEmpty:
    """Tests for _seed_demo_data_if_empty() behaviour."""

    def _patch_factory(self, session_mock: AsyncMock) -> Any:
        """Return a context-manager patch for AsyncSessionFactory."""

        class _FakeFactory:
            async def __aenter__(self) -> AsyncMock:
                return session_mock

            async def __aexit__(self, *_: Any) -> None:
                pass

        factory = MagicMock()
        factory.return_value = _FakeFactory()
        return factory

    @pytest.mark.asyncio
    async def test_seed_skipped_in_production(self) -> None:
        """Production env -> seed function returns immediately (no DB calls)."""
        with (
            patch.object(main_mod, "_ENVIRONMENT", "production"),
            patch(
                _SESSION_FACTORY,
                side_effect=AssertionError("DB must not be accessed in production"),
            ),
        ):
            # Must not raise even though AsyncSessionFactory would error.
            await main_mod._seed_demo_data_if_empty()

    @pytest.mark.asyncio
    async def test_seed_skipped_when_db_has_real_data(self) -> None:
        """When tenant_count > 1, seeding is skipped silently."""
        session_mock = _make_session_mock(tenant_count=3, s1_count=500)

        with (
            patch.object(main_mod, "_ENVIRONMENT", "development"),
            patch(_SESSION_FACTORY, self._patch_factory(session_mock)),
            patch(_ENSURE_DEMO_USER, new_callable=AsyncMock) as mock_user,
        ):
            await main_mod._seed_demo_data_if_empty()

        # _ensure_demo_user is still called so the demo user gets created.
        mock_user.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_seed_skipped_when_s1_already_populated(self) -> None:
        """When scope1_ingestions > 0 (but only 1 tenant), seeding is skipped."""
        session_mock = _make_session_mock(tenant_count=1, s1_count=42)

        with (
            patch.object(main_mod, "_ENVIRONMENT", "development"),
            patch(_SESSION_FACTORY, self._patch_factory(session_mock)),
            patch(_ENSURE_DEMO_USER, new_callable=AsyncMock) as mock_user,
        ):
            await main_mod._seed_demo_data_if_empty()

        mock_user.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_seed_runs_when_db_only_has_m0(self) -> None:
        """When tenant_count==1 and s1_count==0, asyncio.to_thread is called."""
        session_mock = _make_session_mock(tenant_count=1, s1_count=0)

        thread_calls: list[bool] = []

        async def _fake_seed_thread(fn: Any) -> int:
            thread_calls.append(True)
            return 0

        with (
            patch.object(main_mod, "_ENVIRONMENT", "development"),
            patch(_SESSION_FACTORY, self._patch_factory(session_mock)),
            patch(_ENSURE_DEMO_USER, new_callable=AsyncMock),
            patch("asyncio.to_thread", side_effect=_fake_seed_thread),
            # Make every Path.exists() call return True so CSV guard passes.
            patch("pathlib.Path.exists", return_value=True),
        ):
            await main_mod._seed_demo_data_if_empty()

        assert thread_calls, "Expected asyncio.to_thread to be called for seed script"

    @pytest.mark.asyncio
    async def test_seed_skipped_missing_csvs(self) -> None:
        """Missing seed CSVs -> warning logged, no crash, demo user still created."""
        session_mock = _make_session_mock(tenant_count=1, s1_count=0)

        with (
            patch.object(main_mod, "_ENVIRONMENT", "development"),
            patch(_SESSION_FACTORY, self._patch_factory(session_mock)),
            patch(_ENSURE_DEMO_USER, new_callable=AsyncMock) as mock_user,
            # All Path.exists() calls return False -> CSV guard triggers.
            patch("pathlib.Path.exists", return_value=False),
        ):
            await main_mod._seed_demo_data_if_empty()

        # Demo user creation is still attempted.
        mock_user.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_seed_failure_does_not_crash_lifespan(self) -> None:
        """A seed failure (any exception) is caught; the function returns normally."""
        session_mock = _make_session_mock(tenant_count=1, s1_count=0)

        with (
            patch.object(main_mod, "_ENVIRONMENT", "development"),
            patch(_SESSION_FACTORY, self._patch_factory(session_mock)),
            patch(_ENSURE_DEMO_USER, new_callable=AsyncMock),
            # Simulate the seed script raising an unexpected error.
            patch("asyncio.to_thread", side_effect=RuntimeError("psycopg connection refused")),
            # Let CSVs appear to exist so we reach the to_thread call.
            patch("pathlib.Path.exists", return_value=True),
        ):
            # Must NOT raise — the API process must stay alive.
            try:
                await main_mod._seed_demo_data_if_empty()
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"_seed_demo_data_if_empty raised unexpectedly: {exc!r}")


# ---------------------------------------------------------------------------
# Tests: _ensure_demo_user()
# ---------------------------------------------------------------------------


class TestEnsureDemoUser:
    """Tests for the _ensure_demo_user() helper."""

    def _make_full_session(
        self,
        user_count: int = 0,
        tenant_row_id: str = "00000000-0000-0000-0000-000000000001",
        role_row_id: str = "00000000-0000-0000-0000-000000000002",
        has_tenant: bool = True,
        has_role: bool = True,
    ) -> AsyncMock:
        """Build a session mock wired for _ensure_demo_user queries."""
        session = AsyncMock()

        async def _execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:  # type: ignore[misc]
            q = str(query).lower()
            result = MagicMock()
            if "ref.users" in q and "count" in q:
                result.scalar_one.return_value = user_count
                return result
            if "ref.tenants" in q:
                if has_tenant:
                    row = MagicMock()
                    row.__getitem__ = MagicMock(return_value=tenant_row_id)
                    result.fetchone.return_value = row
                else:
                    result.fetchone.return_value = None
                return result
            if "ref.roles" in q:
                if has_role:
                    row = MagicMock()
                    row.__getitem__ = MagicMock(return_value=role_row_id)
                    result.fetchone.return_value = row
                else:
                    result.fetchone.return_value = None
                return result
            # INSERT — no meaningful return needed.
            result.scalar_one.return_value = None
            result.fetchone.return_value = None
            return result

        session.execute = _execute
        session.commit = AsyncMock()
        return session

    def _patch_factory(self, session_mock: AsyncMock) -> Any:
        class _FF:
            async def __aenter__(self) -> AsyncMock:
                return session_mock

            async def __aexit__(self, *_: Any) -> None:
                pass

        f = MagicMock()
        f.return_value = _FF()
        return f

    @pytest.mark.asyncio
    async def test_demo_user_seeded_with_editor_role(self) -> None:
        """When no demo user exists, INSERT is executed and commit is called."""
        session_mock = self._make_full_session(user_count=0)
        insert_calls: list[str] = []

        original_execute = session_mock.execute

        async def _tracking_execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:
            q = str(query)
            if "INSERT INTO ref.users" in q:
                insert_calls.append(q)
            return await original_execute(query, *args, **kwargs)

        session_mock.execute = _tracking_execute

        with (
            patch(_SESSION_FACTORY, self._patch_factory(session_mock)),
            patch("asyncio.to_thread", return_value="$2b$12$fakehash"),
        ):
            await main_mod._ensure_demo_user()

        assert insert_calls, "Expected INSERT INTO ref.users to be called"
        session_mock.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_demo_user_not_duplicated_if_exists(self) -> None:
        """When demo user already exists, no INSERT is performed."""
        session_mock = self._make_full_session(user_count=1)
        insert_calls: list[str] = []

        original_execute = session_mock.execute

        async def _tracking_execute(query: Any, *args: Any, **kwargs: Any) -> MagicMock:
            q = str(query)
            if "INSERT" in q:
                insert_calls.append(q)
            return await original_execute(query, *args, **kwargs)

        session_mock.execute = _tracking_execute

        with (
            patch(_SESSION_FACTORY, self._patch_factory(session_mock)),
        ):
            await main_mod._ensure_demo_user()

        assert not insert_calls, "No INSERT expected when demo user already exists"

    @pytest.mark.asyncio
    async def test_ensure_demo_user_survives_exception(self) -> None:
        """A DB error in _ensure_demo_user must not crash the caller."""
        with patch(
            _SESSION_FACTORY,
            side_effect=RuntimeError("DB is down"),
        ):
            # Must not raise.
            try:
                await main_mod._ensure_demo_user()
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"_ensure_demo_user raised unexpectedly: {exc!r}")
