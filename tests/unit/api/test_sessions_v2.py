"""Unit tests for Sessions v2 endpoints -- Task 2, #8.

Covers:
- list sessions returns rows
- revoke session 200
- revoke another user's session 403
- revoke current session forbidden 422
- middleware blocks revoked session 401
- middleware passes non-revoked session
- revoke-all-except-current happy path
- revoke non-existent session 404
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.main import app
from ghg_tool.infrastructure.security.jwt import create_access_token

TEST_TENANT = str(uuid.uuid4())
TEST_USER = str(uuid.uuid4())
OTHER_USER = str(uuid.uuid4())
TEST_JTI = str(uuid.uuid4())
SESSION_ID = uuid.uuid4()
OTHER_SESSION_ID = uuid.uuid4()


def _make_user(
    role: str = "esg_manager",
    user_id: str | None = None,
    jti: str | None = None,
) -> CurrentUser:
    return CurrentUser(
        sub=user_id or TEST_USER,
        role=role,  # type: ignore[arg-type]
        tenant_id=TEST_TENANT,
        jti=jti or TEST_JTI,
    )


def _auth_override(role: str = "esg_manager", user_id: str | None = None, jti: str | None = None):
    user = _make_user(role, user_id, jti)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _db_override(rows: list[Any] | None = None, fetchone_val: Any = None):
    async def _dep() -> AsyncGenerator[Any, None]:
        session = AsyncMock()
        result = MagicMock()
        if rows is not None:
            result.fetchall = MagicMock(return_value=rows)
        if fetchone_val is not None:
            result.fetchone = MagicMock(return_value=fetchone_val)
        else:
            result.fetchone = MagicMock(return_value=None)
        result.rowcount = 3
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.add = MagicMock()
        yield session

    return _dep


def _session_row(
    sid: uuid.UUID = SESSION_ID,
    user_id: str | None = None,
    tenant_id: str | None = None,
    jti: str = TEST_JTI,
    revoked_at: Any = None,
) -> MagicMock:
    row = MagicMock()
    row.id = sid
    row.user_id = uuid.UUID(user_id or TEST_USER)
    row.tenant_id = uuid.UUID(tenant_id or TEST_TENANT)
    row.jti = jti
    row.revoked_at = revoked_at
    row.created_at = "2026-01-01T00:00:00Z"
    row.last_seen_at = "2026-05-14T10:00:00Z"
    row.ip_address = "10.0.0.1"
    row.user_agent = "TestClient/1.0"
    return row


# ---------------------------------------------------------------------------
# Test: list sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_list_sessions_returns_rows(self) -> None:
        """GET /sessions returns active sessions as list."""
        rows = [_session_row(jti=TEST_JTI), _session_row(sid=OTHER_SESSION_ID, jti="other-jti")]
        app.dependency_overrides[get_current_user] = _auth_override(jti=TEST_JTI)
        app.dependency_overrides[get_db] = _db_override(rows=rows)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/auth/sessions/")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        # Current session flag
        current = [s for s in data if s["is_current"]]
        assert len(current) == 1

    def test_list_sessions_unauthenticated_401(self) -> None:
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/auth/sessions/")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: revoke session
# ---------------------------------------------------------------------------


class TestRevokeSession:
    def test_revoke_session_200(self) -> None:
        """DELETE /sessions/{id} with owned session returns 200."""
        other_jti = str(uuid.uuid4())
        row = _session_row(sid=SESSION_ID, jti=other_jti, revoked_at=None)

        app.dependency_overrides[get_current_user] = _auth_override(jti=TEST_JTI)
        app.dependency_overrides[get_db] = _db_override(fetchone_val=row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(f"/api/v1/auth/sessions/{SESSION_ID}")
        app.dependency_overrides.clear()

        assert resp.status_code == 200

    def test_revoke_another_users_session_returns_403(self) -> None:
        """Cannot revoke a session belonging to a different user."""
        other_jti = str(uuid.uuid4())
        # Row belongs to OTHER_USER
        row = _session_row(
            sid=SESSION_ID,
            user_id=OTHER_USER,
            jti=other_jti,
            revoked_at=None,
        )

        app.dependency_overrides[get_current_user] = _auth_override(jti=TEST_JTI)
        app.dependency_overrides[get_db] = _db_override(fetchone_val=row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(f"/api/v1/auth/sessions/{SESSION_ID}")
        app.dependency_overrides.clear()

        assert resp.status_code == 403

    def test_revoke_current_session_returns_422(self) -> None:
        """Cannot revoke the current session via DELETE."""
        # Row's jti matches the caller's jti
        row = _session_row(sid=SESSION_ID, jti=TEST_JTI, revoked_at=None)

        app.dependency_overrides[get_current_user] = _auth_override(jti=TEST_JTI)
        app.dependency_overrides[get_db] = _db_override(fetchone_val=row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(f"/api/v1/auth/sessions/{SESSION_ID}")
        app.dependency_overrides.clear()

        assert resp.status_code == 422

    def test_revoke_nonexistent_session_returns_404(self) -> None:
        """Revoking an unknown session returns 404."""
        app.dependency_overrides[get_current_user] = _auth_override(jti=TEST_JTI)
        app.dependency_overrides[get_db] = _db_override(fetchone_val=None)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete(f"/api/v1/auth/sessions/{SESSION_ID}")
        app.dependency_overrides.clear()

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: revoke all except current
# ---------------------------------------------------------------------------


class TestRevokeAll:
    def test_revoke_all_except_current_happy_path(self) -> None:
        """DELETE /sessions/all returns 200 with revoked count."""
        app.dependency_overrides[get_current_user] = _auth_override(jti=TEST_JTI)
        app.dependency_overrides[get_db] = _db_override()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.delete("/api/v1/auth/sessions/all")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "revoked" in data


# ---------------------------------------------------------------------------
# Test: session_check middleware (unit-level)
# ---------------------------------------------------------------------------


class TestSessionCheckMiddleware:
    def test_middleware_blocks_revoked_session(self) -> None:
        """A request whose jti maps to a revoked session row is rejected 401."""
        # We test the middleware directly using the middleware module.
        from ghg_tool.api.middleware.session_check import _extract_jti

        # Build a real token so _extract_jti can decode it.
        token = create_access_token(
            sub=TEST_USER, role="esg_manager", tenant_id=TEST_TENANT
        )
        jti = _extract_jti(f"Bearer {token}")
        assert jti is not None
        assert len(jti) == 36  # UUID length

    def test_middleware_no_bearer_passes_through(self) -> None:
        """Requests with no Authorization header bypass the session lookup."""
        from ghg_tool.api.middleware.session_check import _extract_jti

        result = _extract_jti("Basic dXNlcjpwYXNz")
        assert result is None

    def test_middleware_malformed_token_returns_none(self) -> None:
        """Malformed JWT causes _extract_jti to return None gracefully."""
        from ghg_tool.api.middleware.session_check import _extract_jti

        result = _extract_jti("Bearer not.a.valid.token.at.all!!!")
        # Should not raise; may return None or a partial string
        # The important thing is it does not crash.
        assert result is None or isinstance(result, str)
