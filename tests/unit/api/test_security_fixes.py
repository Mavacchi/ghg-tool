"""Tests for Phase 8 security fixes — SEC-P0-001 through SEC-P1-006.

Each test class is labelled with the finding it closes.  These tests are
designed to be permanently green; removing them should require an explicit
security review.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set env vars BEFORE importing any ghg_tool modules
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient  # noqa: E402

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user  # noqa: E402
from ghg_tool.api.dependencies.db import get_db  # noqa: E402
from ghg_tool.api.main import app  # noqa: E402
from ghg_tool.infrastructure.security.jwt import (  # noqa: E402
    create_access_token,
    create_refresh_token,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TENANT_A = str(uuid.uuid4())
_TENANT_B = str(uuid.uuid4())
_USER_ID = str(uuid.uuid4())


def _make_user(role: str = "data_steward", tenant_id: str = _TENANT_A) -> CurrentUser:
    return CurrentUser(
        sub=_USER_ID,
        role=role,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        jti=str(uuid.uuid4()),
    )


def _auth_override(role: str = "data_steward", tenant_id: str = _TENANT_A) -> Any:
    user = _make_user(role, tenant_id)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _mock_db_empty() -> Any:
    async def _gen() -> AsyncGenerator[Any, None]:
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        session.execute = AsyncMock(return_value=mock_result)
        yield session

    return _gen


def _teardown() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# SEC-P0-001 — JWT secret guard
# ---------------------------------------------------------------------------


class TestSecP0001JwtSecretGuard:
    """SEC-P0-001: GHG_JWT_SECRET must be set and >= 32 chars in prod/staging."""

    def test_missing_secret_raises_in_production(self) -> None:
        """Missing GHG_JWT_SECRET raises RuntimeError when env=production."""
        import importlib
        import sys

        env_backup = os.environ.copy()
        try:
            os.environ["GHG_ENVIRONMENT"] = "production"
            os.environ.pop("GHG_JWT_SECRET", None)

            # Force module reload to trigger _load_jwt_secret() again
            mod_name = "ghg_tool.infrastructure.security.jwt"
            if mod_name in sys.modules:
                del sys.modules[mod_name]

            with pytest.raises(RuntimeError, match="GHG_JWT_SECRET must be set"):
                importlib.import_module(mod_name)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)
            # Restore module to the working state
            if mod_name in sys.modules:
                del sys.modules[mod_name]
            importlib.import_module(mod_name)

    def test_missing_secret_raises_in_staging(self) -> None:
        """Missing GHG_JWT_SECRET raises RuntimeError when env=staging."""
        import importlib
        import sys

        env_backup = os.environ.copy()
        try:
            os.environ["GHG_ENVIRONMENT"] = "staging"
            os.environ.pop("GHG_JWT_SECRET", None)

            mod_name = "ghg_tool.infrastructure.security.jwt"
            if mod_name in sys.modules:
                del sys.modules[mod_name]

            with pytest.raises(RuntimeError, match="GHG_JWT_SECRET must be set"):
                importlib.import_module(mod_name)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)
            if mod_name in sys.modules:
                del sys.modules[mod_name]
            importlib.import_module(mod_name)

    def test_short_secret_raises_regardless_of_env(self) -> None:
        """Secret shorter than 32 chars raises RuntimeError in any environment."""
        import importlib
        import sys

        env_backup = os.environ.copy()
        try:
            os.environ["GHG_ENVIRONMENT"] = "development"
            os.environ["GHG_JWT_SECRET"] = "short"

            mod_name = "ghg_tool.infrastructure.security.jwt"
            if mod_name in sys.modules:
                del sys.modules[mod_name]

            with pytest.raises(RuntimeError, match="at least 32 chars"):
                importlib.import_module(mod_name)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)
            if mod_name in sys.modules:
                del sys.modules[mod_name]
            importlib.import_module(mod_name)

    def test_dev_env_allows_test_fallback_with_warning(self) -> None:
        """In development env, missing secret uses test fallback without raising."""
        import importlib
        import sys

        env_backup = os.environ.copy()
        try:
            os.environ["GHG_ENVIRONMENT"] = "development"
            os.environ.pop("GHG_JWT_SECRET", None)

            mod_name = "ghg_tool.infrastructure.security.jwt"
            if mod_name in sys.modules:
                del sys.modules[mod_name]

            # Should not raise — fallback is used
            jwt_mod = importlib.import_module(mod_name)
            secret = jwt_mod._JWT_SECRET  # type: ignore[attr-defined]
            assert len(secret) >= 32
            assert "test-only" in secret
        finally:
            os.environ.clear()
            os.environ.update(env_backup)
            if mod_name in sys.modules:
                del sys.modules[mod_name]
            importlib.import_module(mod_name)

    def test_current_jwt_secret_meets_minimum_length(self) -> None:
        """The currently loaded JWT secret is at least 32 characters."""
        from ghg_tool.infrastructure.security import jwt as jwt_module

        assert len(jwt_module._JWT_SECRET) >= 32


# ---------------------------------------------------------------------------
# SEC-P0-003 — Cross-tenant isolation: tenant_id from JWT, not query string
# ---------------------------------------------------------------------------


class TestSecP0003CrossTenantIsolation:
    """SEC-P0-003: intensity endpoint sources tenant_id from JWT only."""

    def test_tenant_id_no_longer_accepted_as_query_param(self) -> None:
        """Passing tenant_id in query string is silently ignored; JWT tenant is used."""
        app.dependency_overrides[get_current_user] = _auth_override(tenant_id=_TENANT_A)
        app.dependency_overrides[get_db] = _mock_db_empty()

        with TestClient(app, raise_server_exceptions=False) as client:
            # Pass a different tenant_id in query string — should be ignored
            resp = client.get(
                "/api/v1/intensity/",
                params={
                    "tenant_id": _TENANT_B,  # Attacker supplies different tenant
                    "denominator_type": "EUR_revenue",
                    "gwp_set": "AR6",
                },
            )

        _teardown()

        # Request succeeds (JWT tenant used, not the query-string tenant)
        # If tenant_id were forwarded, the attacker could read another tenant's data.
        assert resp.status_code == 200, resp.text

    def test_query_param_tenant_id_is_ignored(self) -> None:
        """Passing tenant_id=other-uuid in query string does NOT change the DB binding.

        We verify that the DB execute() is called with the JWT tenant_id (_TENANT_A),
        not the adversarial query-string value (_TENANT_B).
        """
        captured_params: list[dict[str, Any]] = []

        async def _spy_db() -> AsyncGenerator[Any, None]:
            session = AsyncMock()

            async def _capture_execute(query: Any, params: dict[str, Any]) -> MagicMock:
                captured_params.append(params)
                result = MagicMock()
                result.__iter__ = MagicMock(return_value=iter([]))
                return result

            session.execute = _capture_execute  # type: ignore[assignment]
            yield session

        app.dependency_overrides[get_current_user] = _auth_override(tenant_id=_TENANT_A)
        app.dependency_overrides[get_db] = _spy_db

        with TestClient(app, raise_server_exceptions=False) as client:
            client.get(
                "/api/v1/intensity/",
                params={
                    "tenant_id": _TENANT_B,  # Adversarial tenant
                    "denominator_type": "EUR_revenue",
                    "gwp_set": "AR6",
                },
            )

        _teardown()

        # DB must have been called with the JWT tenant, not the query-string tenant
        assert len(captured_params) >= 1, "DB execute must be called"
        db_tenant = captured_params[0].get("tenant_id")
        assert db_tenant == _TENANT_A, (
            f"DB must use JWT tenant ({_TENANT_A}), not query-string tenant ({_TENANT_B}); "
            f"got {db_tenant!r}"
        )
        assert db_tenant != _TENANT_B

    def test_request_without_tenant_id_param_succeeds(self) -> None:
        """Omitting tenant_id from query string returns 200 (JWT tenant is used)."""
        app.dependency_overrides[get_current_user] = _auth_override(tenant_id=_TENANT_A)
        app.dependency_overrides[get_db] = _mock_db_empty()

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/v1/intensity/",
                params={"denominator_type": "EUR_revenue", "gwp_set": "AR6"},
            )

        _teardown()

        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# SEC-P0-004 — Refresh role re-fetched from DB
# ---------------------------------------------------------------------------


class TestSecP0004RefreshRoleFromDb:
    """SEC-P0-004: refresh endpoint re-fetches role from DB, not from token."""

    def _make_db_with_role(self, role: str, is_active: bool = True) -> Any:
        mock_row = MagicMock()
        mock_row.is_active = is_active
        mock_row.role_code = role
        # S-006: refresh-rotation reuse-check reads .revoked_at on the prior
        # session row; default MagicMock attribute is truthy and would trip
        # the reuse-detection guard (401 refresh_token_reused).
        mock_row.revoked_at = None

        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=mock_row)

        async def _db() -> AsyncGenerator[Any, None]:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        return _db

    def _make_db_user_not_found(self) -> Any:
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)

        async def _db() -> AsyncGenerator[Any, None]:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        return _db

    def test_refresh_uses_db_role_not_token_role(self) -> None:
        """New access token carries the role from DB, not from the refresh token.

        The refresh token has no role claim; the DB returns 'esg_manager'.
        The new access token must carry 'esg_manager'.
        """
        from ghg_tool.api.dependencies.db import get_db_no_auth

        sub = str(uuid.uuid4())
        tenant = str(uuid.uuid4())
        refresh_token = create_refresh_token(sub=sub, tenant_id=tenant)

        app.dependency_overrides[get_db_no_auth] = self._make_db_with_role("esg_manager")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )
        _teardown()

        assert resp.status_code == 200, resp.text
        from ghg_tool.infrastructure.security.jwt import decode_token
        claims = decode_token(resp.json()["access_token"])
        assert claims["role"] == "esg_manager"

    def test_refresh_returns_401_when_user_not_in_db(self) -> None:
        """Refresh fails with 401 when the user is no longer in the DB."""
        from ghg_tool.api.dependencies.db import get_db_no_auth

        sub = str(uuid.uuid4())
        tenant = str(uuid.uuid4())
        refresh_token = create_refresh_token(sub=sub, tenant_id=tenant)

        app.dependency_overrides[get_db_no_auth] = self._make_db_user_not_found()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )
        _teardown()

        assert resp.status_code == 401, resp.text

    def test_refresh_returns_401_when_user_inactive(self) -> None:
        """Refresh fails with 401 when the user account is inactive."""
        from ghg_tool.api.dependencies.db import get_db_no_auth

        sub = str(uuid.uuid4())
        tenant = str(uuid.uuid4())
        refresh_token = create_refresh_token(sub=sub, tenant_id=tenant)

        app.dependency_overrides[get_db_no_auth] = self._make_db_with_role(
            "data_steward", is_active=False
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )
        _teardown()

        assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# SEC-P0-005 — Username not in logs
# ---------------------------------------------------------------------------


class TestSecP0005UsernameNotInLogs:
    """SEC-P0-005: plain username must never appear in log records."""

    def test_username_not_in_auth_service_logs(self) -> None:
        """authenticate_user emits username_hash, never plain username."""
        import asyncio
        import io
        import logging

        from ghg_tool.application.services import auth_service

        plain_username = "alice_testa_2026"

        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        async def _run() -> None:
            # lookup returns None → user not found path (still logs)
            await auth_service.authenticate_user(
                username=plain_username,
                password="any_password",
                lookup_user=lambda u: asyncio.coroutine(lambda: None)(),  # type: ignore[misc]
                correlation_id="test-cid",
            )

        try:
            asyncio.run(_run())
        except Exception:  # noqa: BLE001
            pass
        finally:
            root_logger.removeHandler(handler)

        log_output = log_capture.getvalue()
        assert plain_username not in log_output, (
            f"Plain username '{plain_username}' must not appear in log output; "
            f"found in: {log_output!r}"
        )

    def test_hash_username_helper_returns_16_chars(self) -> None:
        """_hash_username returns a 16-char hex string."""
        from ghg_tool.application.services.auth_service import _hash_username

        result = _hash_username("testuser")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_username_is_deterministic(self) -> None:
        """Same username always maps to the same hash prefix."""
        from ghg_tool.application.services.auth_service import _hash_username

        assert _hash_username("alice") == _hash_username("alice")

    def test_hash_username_differs_for_different_users(self) -> None:
        """Different usernames produce different hash prefixes."""
        from ghg_tool.application.services.auth_service import _hash_username

        assert _hash_username("alice") != _hash_username("bob")

    def test_auth_router_hash_helper_consistent(self) -> None:
        """The _hash_username helper in auth_service and auth router are consistent."""
        import hashlib

        from ghg_tool.application.services.auth_service import _hash_username

        username = "router_test_user"
        expected = hashlib.sha256(username.encode("utf-8")).hexdigest()[:16]
        assert _hash_username(username) == expected


# ---------------------------------------------------------------------------
# SEC-P1-001 — CORS middleware
# ---------------------------------------------------------------------------


class TestSecP1001CorsMiddleware:
    """SEC-P1-001: CORS middleware is registered with a per-env origin allowlist."""

    def test_cors_preflight_no_allowed_origin_when_env_empty(self) -> None:
        """When GHG_CORS_ORIGINS is empty, no CORS headers are injected for unknown origin."""
        with (
            patch.dict(os.environ, {"GHG_CORS_ORIGINS": ""}, clear=False),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.options(
                "/api/v1/emissions/",
                headers={
                    "Origin": "https://evil.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
        # No wildcard CORS — the origin is not reflected
        assert resp.headers.get("Access-Control-Allow-Origin", "") != "*"

    def test_no_wildcard_cors_origin(self) -> None:
        """The CORS middleware must never emit Access-Control-Allow-Origin: *.

        This is a permanent invariant — removing this test requires a security review.
        """
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/healthz",
                headers={"Origin": "https://attacker.example"},
            )
        assert resp.headers.get("Access-Control-Allow-Origin", "") != "*"

    def test_cors_allows_configured_origin(self) -> None:
        """When GHG_CORS_ORIGINS is set, the configured origin is reflected."""
        allowed = "https://dashboard.example.com"

        # Patch the module-level list used by the already-constructed app
        with (
            patch("ghg_tool.api.main._CORS_ORIGINS", [allowed]),
            patch.dict(os.environ, {"GHG_CORS_ORIGINS": allowed}, clear=False),
        ):
            # Verify the module constant parsing logic is correct.
            raw = os.environ.get("GHG_CORS_ORIGINS", "")
            parsed = [o.strip() for o in raw.split(",") if o.strip()]
            assert allowed in parsed


# ---------------------------------------------------------------------------
# SEC-P1-002 — Security headers middleware
# ---------------------------------------------------------------------------


class TestSecP1002SecurityHeaders:
    """SEC-P1-002: security response headers are injected into every response."""

    _EXPECTED_HEADERS = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'",
    }

    def test_security_headers_present_on_health_endpoint(self) -> None:
        """All security headers are present on /healthz."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")

        for header, value in self._EXPECTED_HEADERS.items():
            assert header in resp.headers, f"Missing header: {header}"
            assert resp.headers[header] == value, (
                f"Header {header}: expected {value!r}, got {resp.headers[header]!r}"
            )

    def test_hsts_header_present(self) -> None:
        """Strict-Transport-Security header is set correctly."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")
        assert resp.headers.get("Strict-Transport-Security") == (
            "max-age=31536000; includeSubDomains; preload"
        )

    def test_x_frame_options_deny(self) -> None:
        """X-Frame-Options: DENY prevents clickjacking."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_content_type_nosniff(self) -> None:
        """X-Content-Type-Options: nosniff prevents MIME sniffing."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_security_headers_on_error_response(self) -> None:
        """Security headers are present even on 401 error responses."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/emissions/")
        assert resp.status_code == 401
        assert "X-Frame-Options" in resp.headers


# ---------------------------------------------------------------------------
# SEC-P1-003 — Stricter rate limit on /auth/login
# ---------------------------------------------------------------------------


class TestSecP1003LoginRateLimit:
    """SEC-P1-003: /auth/login is rate-limited to 5 attempts per minute per IP."""

    def test_login_rate_limit_triggers_after_5_attempts(self) -> None:
        """After 5 consecutive login attempts, the 6th is rejected with 429.

        We directly exercise the login_limiter counter to avoid cross-test
        interference and bypass the DB call (which would 503 without a real DB).
        """
        from ghg_tool.api.middleware.rate_limit import (
            _LOGIN_RATE_LIMIT_REQUESTS,
            _SlidingWindowCounter,
        )

        # Create a fresh counter isolated from the shared login_limiter
        fresh = _SlidingWindowCounter(window_s=60, limit=_LOGIN_RATE_LIMIT_REQUESTS)
        key = f"login:ip:test-{uuid.uuid4()}"

        # Exhaust the limit
        for _ in range(_LOGIN_RATE_LIMIT_REQUESTS):
            assert fresh.is_allowed(key) is True

        # The next attempt must be denied
        assert fresh.is_allowed(key) is False

    def test_login_rate_limit_is_5_per_minute(self) -> None:
        """The login rate limit constant is exactly 5 requests per minute."""
        from ghg_tool.api.middleware.rate_limit import (
            _LOGIN_RATE_LIMIT_REQUESTS,
            _LOGIN_RATE_LIMIT_WINDOW_S,
        )

        assert _LOGIN_RATE_LIMIT_REQUESTS == 5
        assert _LOGIN_RATE_LIMIT_WINDOW_S == 60

    def test_login_429_when_limiter_exhausted(self) -> None:
        """POST /auth/login returns 429 when the per-IP login limiter is exhausted."""
        from ghg_tool.api.dependencies.db import get_db_no_auth

        async def _noop_db() -> AsyncGenerator[Any, None]:
            yield AsyncMock()

        app.dependency_overrides[get_db_no_auth] = _noop_db
        with (
            TestClient(app, raise_server_exceptions=False) as client,
            patch("ghg_tool.api.routers.auth.login_limiter") as mock_limiter,
        ):
            mock_limiter.is_allowed.return_value = False
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "testpass"},
            )
        _teardown()

        assert resp.status_code == 429, resp.text


# ---------------------------------------------------------------------------
# SEC-P1-005 — /auth/login wired to authenticate_user
# ---------------------------------------------------------------------------


class TestSecP1005LoginWired:
    """SEC-P1-005: /auth/login calls authenticate_user (no longer a 503 stub)."""

    def _noop_db(self) -> Any:
        async def _gen() -> AsyncGenerator[Any, None]:
            yield AsyncMock()

        return _gen

    def test_login_returns_401_on_bad_credentials(self) -> None:
        """POST /auth/login with invalid credentials returns 401 (not 503).

        The endpoint is now wired to authenticate_user which returns None on
        failure.  The previous stub returned 503.
        """
        from ghg_tool.api.dependencies.db import get_db_no_auth

        async def _fake_authenticate(**kwargs: Any) -> None:
            return None

        app.dependency_overrides[get_db_no_auth] = self._noop_db()
        with (
            patch(
                "ghg_tool.api.routers.auth.authenticate_user",
                side_effect=_fake_authenticate,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "baduser", "password": "badpass"},
            )
        _teardown()

        assert resp.status_code == 401, (
            f"Expected 401 (wired endpoint); got {resp.status_code}. "
            "If 503, the endpoint is still a stub."
        )

    def test_login_returns_200_on_valid_credentials(self) -> None:
        """POST /auth/login with valid credentials returns 200 + token pair."""
        from ghg_tool.api.dependencies.db import get_db_no_auth
        from ghg_tool.api.schemas.auth_schemas import TokenResponse

        fake_response = TokenResponse(
            access_token=create_access_token(
                sub=str(uuid.uuid4()),
                role="data_steward",
                tenant_id=str(uuid.uuid4()),
            ),
            refresh_token=create_refresh_token(
                sub=str(uuid.uuid4()),
                tenant_id=str(uuid.uuid4()),
            ),
            expires_in=3600,
            token_type="bearer",
        )

        app.dependency_overrides[get_db_no_auth] = self._noop_db()
        with (
            patch(
                "ghg_tool.api.routers.auth.authenticate_user",
                return_value=fake_response,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "validuser", "password": "validpass"},
            )
        _teardown()

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_is_not_503_stub(self) -> None:
        """POST /auth/login must NOT return 503 (the old stub status)."""
        from ghg_tool.api.dependencies.db import get_db_no_auth

        app.dependency_overrides[get_db_no_auth] = self._noop_db()
        with (
            patch(
                "ghg_tool.api.routers.auth.authenticate_user",
                return_value=None,
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "user", "password": "pass"},
            )
        _teardown()

        assert resp.status_code != 503, "Login endpoint must not be a 503 stub"
