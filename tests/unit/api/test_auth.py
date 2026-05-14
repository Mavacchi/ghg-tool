"""Unit tests for /api/v1/auth endpoints and the JWT dependency."""

from __future__ import annotations

import os
import time
import uuid

import pytest

os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

from fastapi.testclient import TestClient

from ghg_tool.api.main import app
from ghg_tool.infrastructure.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
)


class TestJWT:
    """Tests for the JWT encode/decode module (infrastructure/security/jwt.py)."""

    def test_create_and_decode_access_token(self) -> None:
        """Access token round-trips with correct claims."""
        sub = str(uuid.uuid4())
        tenant = str(uuid.uuid4())
        token = create_access_token(sub=sub, role="data_steward", tenant_id=tenant)
        claims = decode_token(token)
        assert claims["sub"] == sub
        assert claims["role"] == "data_steward"
        assert claims["tenant_id"] == tenant
        assert claims["token_type"] == "access"

    def test_create_and_decode_refresh_token(self) -> None:
        """Refresh token round-trips with correct claims."""
        sub = str(uuid.uuid4())
        tenant = str(uuid.uuid4())
        token = create_refresh_token(sub=sub, tenant_id=tenant)
        claims = decode_token(token)
        assert claims["sub"] == sub
        assert claims["token_type"] == "refresh"

    def test_alg_none_rejected(self) -> None:
        """Tokens claiming alg=none must be rejected (SG-01).

        jose library raises JWSError for algorithm=none; our decode_token
        either raises ValueError (our explicit check) or JWSError/JWTError
        (jose internal rejection).  Both indicate the token was correctly denied.
        """
        # Construct a JWT-like string with alg=none in the header manually
        import base64
        import json
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "x", "exp": 9999999999}).encode()
        ).rstrip(b"=").decode()
        raw = f"{header}.{payload}."
        with pytest.raises(Exception):  # noqa: B017 — intentional broad catch
            decode_token(raw)

    def test_expired_token_raises(self) -> None:
        """Expired tokens must raise ExpiredSignatureError."""
        import jose.jwt as jose_jwt
        from jose.exceptions import ExpiredSignatureError as JOSE_ESE
        token = jose_jwt.encode(
            {"sub": "x", "exp": int(time.time()) - 10},
            "test-secret-key-for-unit-tests-only",
            algorithm="HS256",
        )
        with pytest.raises(JOSE_ESE):
            decode_token(token)

    def test_unknown_role_rejected_by_dependency(self) -> None:
        """A token with an unknown role raises 401 via the auth dependency."""
        # Forge a token with an invalid role via direct jwt.encode
        import jose.jwt as jose_jwt
        token = jose_jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "role": "superadmin",
                "tenant_id": str(uuid.uuid4()),
                "jti": str(uuid.uuid4()),
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
                "token_type": "access",
            },
            "test-secret-key-for-unit-tests-only",
            algorithm="HS256",
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/api/v1/emissions/",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 401


class TestAuthRouter:
    """Tests for /api/v1/auth endpoints."""

    def test_logout_returns_204(self) -> None:
        """POST /auth/logout returns 204 (no-op in v1)."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 204

    def test_refresh_with_invalid_token_returns_401(self) -> None:
        """POST /auth/refresh with garbage token returns 401."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "not.a.valid.token"},
            )
        assert resp.status_code == 401

    def test_refresh_with_access_token_type_rejected(self) -> None:
        """POST /auth/refresh with an access token (not refresh) returns 401."""
        token = create_access_token(
            sub=str(uuid.uuid4()),
            role="data_steward",
            tenant_id=str(uuid.uuid4()),
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": token},
            )
        assert resp.status_code == 401

    def test_refresh_with_valid_refresh_token(self) -> None:
        """POST /auth/refresh with a valid refresh token returns 200 + new access token.

        SEC-P0-004: the refresh endpoint now re-fetches the role from the DB.
        We mock get_db_no_auth (used by the refresh route) to return a
        synthetic row with role='data_steward'.
        """
        from collections.abc import AsyncGenerator
        from typing import Any
        from unittest.mock import AsyncMock, MagicMock

        from ghg_tool.api.dependencies.db import get_db_no_auth

        sub = str(uuid.uuid4())
        tenant = str(uuid.uuid4())
        refresh_token = create_refresh_token(sub=sub, tenant_id=tenant)

        # Build a mock DB row for the re-fetch
        mock_row = MagicMock()
        mock_row.is_active = True
        mock_row.role_code = "data_steward"

        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=mock_row)

        async def _mock_db() -> AsyncGenerator[Any, None]:
            session = AsyncMock()
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        app.dependency_overrides[get_db_no_auth] = _mock_db
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )
        app.dependency_overrides.pop(get_db_no_auth, None)

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_no_auth_returns_401(self) -> None:
        """Protected endpoint without Authorization header returns 401."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/emissions/")
        assert resp.status_code == 401

    def test_correlation_id_echoed_in_response(self) -> None:
        """X-Correlation-ID sent in request is echoed in response."""
        cid = str(uuid.uuid4())
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get(
                "/healthz",
                headers={"X-Correlation-ID": cid},
            )
        assert resp.headers.get("X-Correlation-ID") == cid

    def test_missing_correlation_id_generates_one(self) -> None:
        """If X-Correlation-ID is absent, a UUID is generated and echoed."""
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/healthz")
        cid = resp.headers.get("X-Correlation-ID", "")
        assert len(cid) == 36  # UUID v4 string length
