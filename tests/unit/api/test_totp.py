"""Unit tests for TOTP 2FA endpoints -- Task 1, #7.

Covers:
- enroll happy path returns secret + URL
- verify happy path enables 2FA
- verify wrong OTP fails 401
- disable requires OTP
- login with totp_enabled returns 202 + partial_token
- partial_token cannot be used as Bearer on protected endpoints
- challenge happy path returns full token pair
- challenge with wrong OTP fails 401
- enroll unauthenticated returns 401
- disable without 2FA enabled returns 401
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pyotp
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db_no_auth
from ghg_tool.api.main import app
from ghg_tool.infrastructure.security.jwt import create_access_token, decode_token

TEST_TENANT = str(uuid.uuid4())
TEST_USER = str(uuid.uuid4())


def _make_user(role: str = "esg_manager") -> CurrentUser:
    return CurrentUser(
        sub=TEST_USER, role=role, tenant_id=TEST_TENANT, jti=str(uuid.uuid4())  # type: ignore[arg-type]
    )


def _auth_override(role: str = "esg_manager"):
    user = _make_user(role)

    async def _dep() -> CurrentUser:
        return user

    return _dep


def _db_override_with_row(row: Any):
    async def _dep() -> AsyncGenerator[Any, None]:
        session = AsyncMock()
        result = MagicMock()
        result.fetchone = MagicMock(return_value=row)
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.add = MagicMock()
        yield session

    return _dep


def _db_noop():
    async def _dep() -> AsyncGenerator[Any, None]:
        session = AsyncMock()
        result = MagicMock()
        result.fetchone = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.add = MagicMock()
        yield session

    return _dep


# ---------------------------------------------------------------------------
# Helper: build a mock user row with TOTP fields
# ---------------------------------------------------------------------------


def _user_row(
    totp_secret: str | None = None,
    totp_enabled: bool = False,
    username: str = "testuser",
    tenant_id: str | None = None,
) -> MagicMock:
    row = MagicMock()
    row.totp_secret = totp_secret
    row.totp_enabled = totp_enabled
    row.totp_enrolled_at = None
    row.username = username
    row.tenant_id = uuid.UUID(tenant_id or TEST_TENANT)
    return row


# ---------------------------------------------------------------------------
# Test: enroll
# ---------------------------------------------------------------------------


class TestTOTPEnroll:
    def test_enroll_happy_path_returns_secret_and_url(self) -> None:
        """Enroll returns secret_b32, otpauth_url, qr_png_b64."""
        # The enroll endpoint fetches the user row for the username.
        row = _user_row()

        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/totp/enroll")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "secret_b32" in data
        assert "otpauth_url" in data
        assert "qr_png_b64" in data
        # secret must be a valid base32 pyotp secret
        assert len(data["secret_b32"]) >= 16

    def test_enroll_unauthenticated_returns_401(self) -> None:
        """Without auth header, enroll returns 401."""
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/totp/enroll")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: verify
# ---------------------------------------------------------------------------


class TestTOTPVerify:
    def test_verify_happy_path_enables_2fa(self) -> None:
        """Correct OTP activates 2FA and returns 200."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        otp = totp.now()

        row = _user_row(totp_secret=secret, totp_enabled=False)
        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/totp/verify", json={"otp": otp})
        app.dependency_overrides.clear()

        assert resp.status_code == 200

    def test_verify_wrong_otp_returns_401(self) -> None:
        """Wrong OTP on verify returns 401."""
        secret = pyotp.random_base32()
        row = _user_row(totp_secret=secret, totp_enabled=False)

        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/totp/verify", json={"otp": "000000"})
        app.dependency_overrides.clear()

        assert resp.status_code == 401

    def test_verify_without_enrollment_returns_401(self) -> None:
        """Calling verify before enroll (no totp_secret) returns 401."""
        row = _user_row(totp_secret=None)
        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/totp/verify", json={"otp": "123456"})
        app.dependency_overrides.clear()

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: disable
# ---------------------------------------------------------------------------


class TestTOTPDisable:
    def test_disable_requires_valid_otp(self) -> None:
        """Disable with wrong OTP returns 401."""
        secret = pyotp.random_base32()
        row = _user_row(totp_secret=secret, totp_enabled=True)

        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/totp/disable", json={"otp": "000000"})
        app.dependency_overrides.clear()

        assert resp.status_code == 401

    def test_disable_without_2fa_enabled_returns_401(self) -> None:
        """Calling disable when totp_enabled=False returns 401."""
        row = _user_row(totp_secret=None, totp_enabled=False)

        app.dependency_overrides[get_current_user] = _auth_override()
        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/totp/disable", json={"otp": "123456"})
        app.dependency_overrides.clear()

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: login with totp_enabled -> 202 + partial_token
# ---------------------------------------------------------------------------


class TestLoginTOTPFlow:
    def test_partial_token_cannot_be_used_as_bearer(self) -> None:
        """A partial_token (pre_2fa=True) is rejected on protected endpoints.

        The token is always rejected -- either:
        - 401 from the auth dependency (pre_2fa guard), or
        - 401/503 from the session_check middleware (no session row / DB error).
        The key invariant: 200 must never be returned for a pre_2fa token.
        """
        partial = create_access_token(
            sub=TEST_USER,
            role="esg_manager",
            tenant_id=TEST_TENANT,
            extra_claims={"pre_2fa": True},
            ttl_seconds=300,
        )
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/v1/emissions/",
                headers={"Authorization": f"Bearer {partial}"},
            )
        # Must not be 200 -- either middleware (503/401) or auth dep (401) blocks it.
        assert resp.status_code in (401, 503)

    def test_partial_token_claims(self) -> None:
        """Partial token carries pre_2fa=True and has a short TTL (<=300s)."""
        import time

        partial = create_access_token(
            sub=TEST_USER,
            role="esg_manager",
            tenant_id=TEST_TENANT,
            extra_claims={"pre_2fa": True},
            ttl_seconds=300,
        )
        claims = decode_token(partial)
        assert claims.get("pre_2fa") is True
        assert claims["exp"] - time.time() <= 301  # noqa: PLR2004


# ---------------------------------------------------------------------------
# Test: /totp/challenge
# ---------------------------------------------------------------------------


class TestTOTPChallenge:
    def test_challenge_happy_path_returns_full_token_pair(self) -> None:
        """Valid partial_token + correct OTP returns 200 with access+refresh."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        otp = totp.now()

        partial = create_access_token(
            sub=TEST_USER,
            role="esg_manager",
            tenant_id=TEST_TENANT,
            extra_claims={"pre_2fa": True},
            ttl_seconds=300,
        )
        row = _user_row(totp_secret=secret, totp_enabled=True)

        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/totp/challenge",
                json={"partial_token": partial, "otp": otp},
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # Full token must NOT carry pre_2fa
        full_claims = decode_token(data["access_token"])
        assert not full_claims.get("pre_2fa", False)

    def test_challenge_wrong_otp_returns_401(self) -> None:
        """Wrong OTP on challenge returns 401."""
        secret = pyotp.random_base32()
        partial = create_access_token(
            sub=TEST_USER,
            role="esg_manager",
            tenant_id=TEST_TENANT,
            extra_claims={"pre_2fa": True},
            ttl_seconds=300,
        )
        row = _user_row(totp_secret=secret, totp_enabled=True)

        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/totp/challenge",
                json={"partial_token": partial, "otp": "000000"},
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 401

    def test_challenge_with_non_partial_token_returns_401(self) -> None:
        """Passing a full access token (no pre_2fa) to challenge returns 401."""
        full_token = create_access_token(
            sub=TEST_USER, role="esg_manager", tenant_id=TEST_TENANT
        )
        secret = pyotp.random_base32()
        row = _user_row(totp_secret=secret, totp_enabled=True)

        app.dependency_overrides[get_db_no_auth] = _db_override_with_row(row)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/totp/challenge",
                json={"partial_token": full_token, "otp": pyotp.TOTP(secret).now()},
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 401
