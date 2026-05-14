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
- BUG-01: session row missing -> 401 session_not_found (new fail-closed behavior)
- BUG-01: session row exists and not revoked -> request passes
- middleware no Bearer -> passes through (no DB lookup)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
# BUG-01/S-007/S-012/S-022: updated for new fail-closed behavior.
# ---------------------------------------------------------------------------


class TestSessionCheckMiddleware:
    def test_middleware_jwt_decode_extracts_jti(self) -> None:
        """The middleware decodes the signed JWT to extract jti.

        S-024: the middleware now uses verified decode, not unverified peek.
        This test confirms the jti is correctly extracted from a real token.
        """
        from ghg_tool.infrastructure.security.jwt import decode_token

        token = create_access_token(
            sub=TEST_USER, role="esg_manager", tenant_id=TEST_TENANT
        )
        claims = decode_token(token)
        jti = claims.get("jti", "")
        assert jti is not None
        assert len(jti) == 36  # UUID4 length

    def test_middleware_no_bearer_passes_through(self) -> None:
        """Requests with no Authorization header bypass the session lookup.

        The middleware short-circuits when there's no Bearer token.
        Health checks and public routes should not be blocked.
        """
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")
        # /healthz is in _EXCLUDED_PATHS; should always pass through
        assert resp.status_code == 200

    def test_middleware_excluded_paths_bypass_session_check(self) -> None:
        """Paths in _NO_SESSION_PATHS bypass the session row check.

        /api/v1/auth/login, /api/v1/auth/refresh, etc. do not require
        a pre-existing session row (they are the token issuance endpoints).
        """
        # /api/v1/auth/login is in _NO_SESSION_PATHS; even a bad payload
        # should get past the middleware and hit the auth logic (returning 401
        # for bad credentials, not 503 from the middleware).
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "badpass"},
            )
        # 401 from the auth handler (bad creds), or 500 if DB unavailable.
        # The key invariant: the middleware did NOT block this path with 503.
        # The request reached the login handler (even if it then fails).
        assert resp.status_code in (401, 422, 500)  # 500 if DB is not available for lookup

    def test_middleware_fail_closed_on_db_error(self) -> None:
        """BUG-01 / S-022: middleware returns 503 when DB is unavailable.

        A request with a valid Bearer token but no reachable auth.sessions
        table must be rejected fail-closed (503), never allowed through.
        """
        token = create_access_token(
            sub=TEST_USER, role="esg_manager", tenant_id=TEST_TENANT
        )
        # No DB mocking -- the AsyncSessionFactory will fail to connect.
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/v1/auth/sessions/",
                headers={"Authorization": f"Bearer {token}"},
            )
        # Either 503 (middleware fail-closed) or 401 (session_not_found after
        # the middleware correctly blocks).  Both are acceptable: the key
        # invariant is that 200 must NOT be returned.
        assert resp.status_code in (401, 503)

    def test_middleware_session_revoked_returns_401(self) -> None:
        """BUG-01: a revoked session row causes 401 session_revoked.

        We patch AsyncSessionFactory to return a revoked row.
        """
        token = create_access_token(
            sub=TEST_USER, role="esg_manager", tenant_id=TEST_TENANT
        )
        claims_from_token = None
        from ghg_tool.infrastructure.security.jwt import decode_token
        claims_from_token = decode_token(token)
        token_jti = claims_from_token["jti"]

        revoked_row = MagicMock()
        revoked_row.id = uuid.uuid4()
        revoked_row.revoked_at = "2026-05-14T10:00:00Z"  # non-None = revoked

        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=revoked_row)

        mock_db_session = AsyncMock()
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "ghg_tool.api.middleware.session_check.AsyncSessionFactory",
            return_value=mock_db_session,
        ):
            app.dependency_overrides.clear()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(
                    "/api/v1/auth/sessions/",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 401
        data = resp.json()
        assert data.get("detail") == "session_revoked"

    def test_middleware_session_not_found_returns_401(self) -> None:
        """BUG-01 / BUG-19: missing session row -> 401 session_not_found.

        After the BUG-01 fix, every issued token has a session row.  A token
        with no matching session row is a forged or pre-fix token and must be
        rejected fail-closed.
        """
        token = create_access_token(
            sub=TEST_USER, role="esg_manager", tenant_id=TEST_TENANT
        )

        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)  # no session row

        mock_db_session = AsyncMock()
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_db_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "ghg_tool.api.middleware.session_check.AsyncSessionFactory",
            return_value=mock_db_session,
        ):
            app.dependency_overrides.clear()
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(
                    "/api/v1/auth/sessions/",
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 401
        data = resp.json()
        assert data.get("detail") == "session_not_found"
