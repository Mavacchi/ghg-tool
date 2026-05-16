"""Shared fixtures for API unit tests.

All DB dependencies are mocked via ``app.dependency_overrides`` so that
tests run without a live PostgreSQL instance.  Tokens are issued with HS256
and the dev secret so that decode_token works in the test environment.
"""

from __future__ import annotations

import importlib
import os
import sys
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Ensure HS256 fallback for tests (no real key files needed)
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app  # noqa: E402 — must come after env setup
from ghg_tool.infrastructure.security.jwt import create_access_token

# ---------------------------------------------------------------------------
# Canonical tenant and user UUIDs for tests (no real PII)
# ---------------------------------------------------------------------------
TEST_TENANT_ID = str(uuid.uuid4())
TEST_USER_ID_DS = str(uuid.uuid4())   # editor
TEST_USER_ID_ESG = str(uuid.uuid4())  # admin
TEST_USER_ID_AU = str(uuid.uuid4())   # viewer


def make_token(role: str, user_id: str | None = None) -> str:
    """Create a HS256 test JWT for the given role.

    Args:
        role: RBAC role code.
        user_id: Optional user sub; defaults to a fresh UUID.

    Returns:
        Signed JWT string.
    """
    return create_access_token(
        sub=user_id or str(uuid.uuid4()),
        role=role,
        tenant_id=TEST_TENANT_ID,
    )


def _make_current_user(role: str, user_id: str | None = None) -> CurrentUser:
    """Build a ``CurrentUser`` for dependency override.

    Args:
        role: RBAC role code.
        user_id: Optional user sub.

    Returns:
        ``CurrentUser`` Pydantic model.
    """
    return CurrentUser(
        sub=user_id or str(uuid.uuid4()),
        role=role,  # type: ignore[arg-type]
        tenant_id=TEST_TENANT_ID,
        jti=str(uuid.uuid4()),
    )


def override_auth(role: str, user_id: str | None = None) -> Any:
    """Return an async dependency override for ``get_current_user``.

    Args:
        role: The role to inject.
        user_id: Optional user UUID string.

    Returns:
        An async callable that returns a ``CurrentUser``.
    """
    user = _make_current_user(role, user_id)

    async def _override() -> CurrentUser:
        return user

    return _override


def override_db_noop() -> Any:
    """Return a no-op async DB session override (avoids DB connection).

    Returns:
        An async generator that yields a MagicMock session.
    """
    async def _override() -> AsyncGenerator[Any, None]:
        yield MagicMock()

    return _override


@pytest.fixture
def client_ds() -> TestClient:
    """Synchronous TestClient with editor auth and no DB."""
    app.dependency_overrides[get_current_user] = override_auth("editor", TEST_USER_ID_DS)
    app.dependency_overrides[get_db] = override_db_noop()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_esg() -> TestClient:
    """Synchronous TestClient with admin auth and no DB."""
    app.dependency_overrides[get_current_user] = override_auth("admin", TEST_USER_ID_ESG)
    app.dependency_overrides[get_db] = override_db_noop()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_auditor() -> TestClient:
    """Synchronous TestClient with viewer auth and no DB."""
    app.dependency_overrides[get_current_user] = override_auth("viewer", TEST_USER_ID_AU)
    app.dependency_overrides[get_db] = override_db_noop()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_auth() -> TestClient:
    """Synchronous TestClient with NO auth override (uses real JWT decode)."""
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# JWT module state isolation (BLOCK: order-dependent flaky tests)
# ---------------------------------------------------------------------------

_JWT_MOD = "ghg_tool.infrastructure.security.jwt"

# Canonical env that every JWT test in this package should see.
_JWT_TEST_ENV = {
    "GHG_JWT_ALGORITHM": "HS256",
    "GHG_JWT_SECRET": "test-secret-key-for-unit-tests-only",
    "GHG_ENVIRONMENT": "development",
}


@pytest.fixture(autouse=True)
def _reset_jwt_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-establish a deterministic JWT module state before every API test.

    test_security_fixes.py::TestSecP0001JwtSecretGuard intentionally reloads
    the jwt module with production env vars (GHG_ENVIRONMENT=production,
    no GHG_JWT_SECRET) to verify the RuntimeError guard fires.  After those
    tests the module is left with a *different* ``_JWT_SECRET`` (the test
    fallback loaded in the final ``importlib.import_module`` call inside their
    finally block) than what the rest of the suite expects.

    This autouse fixture ensures that:
    1. The canonical test env vars are always in place for every test.
    2. The jwt module is reloaded from a clean state so ``_JWT_SECRET`` and
       ``_JWT_ALGORITHM`` are derived from the canonical env, not from whatever
       a prior test left behind.

    The reload is cheap (< 1 ms) and avoids the ordering sensitivity described
    in BLOCK-4 (flaky order-dependent JWT state).
    """
    for key, value in _JWT_TEST_ENV.items():
        monkeypatch.setenv(key, value)

    # Force a clean reload so module-level constants are re-derived from env.
    if _JWT_MOD in sys.modules:
        del sys.modules[_JWT_MOD]
    importlib.import_module(_JWT_MOD)
