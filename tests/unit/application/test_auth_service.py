"""Unit tests for ``auth_service.py`` — authenticate_user + refresh_access_token.

Coverage target: >= 95% line coverage on
``src/ghg_tool/application/services/auth_service.py``.

Design decisions
----------------
- ``authenticate_user`` accepts a ``lookup_user`` callable; we supply async
  lambdas backed by ``MagicMock`` instances so no DB is required.
- ``verify_password`` wraps ``bcrypt.checkpw`` directly (no passlib).
  We patch ``ghg_tool.application.services.auth_service.verify_password``
  to control the return value without the cost of real bcrypt rounds.
- JWT encode/decode uses the real HS256 infrastructure with the test secret
  set by ``os.environ.setdefault`` at module level, consistent with
  ``tests/unit/api/test_auth.py``.
- ``refresh_access_token`` is synchronous.  It catches JWT exceptions
  internally and returns None rather than raising.  Tests assert on the
  None return value or on the TokenResponse shape.
- No DB, no network, no real bcrypt calls in the happy path.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Set JWT env vars BEFORE importing any ghg_tool modules
os.environ.setdefault("GHG_JWT_ALGORITHM", "HS256")
os.environ.setdefault("GHG_JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("GHG_ENVIRONMENT", "development")

import jose.jwt as jose_jwt  # noqa: E402

from ghg_tool.api.schemas.auth_schemas import TokenResponse  # noqa: E402
from ghg_tool.application.services.auth_service import (  # noqa: E402
    authenticate_user,
    refresh_access_token,
)
from ghg_tool.infrastructure.security.jwt import (  # noqa: E402
    create_refresh_token,
    decode_token,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TEST_SECRET = "test-secret-key-for-unit-tests-only"
_TEST_TENANT_ID = str(uuid.uuid4())
_TEST_USER_ID = str(uuid.uuid4())


def _make_user_record(
    *,
    is_active: bool = True,
    role_code: str = "data_steward",
    password_hash: str = "hashed_pw",
) -> MagicMock:
    """Build a mock UserRecord satisfying the auth_service Protocol.

    Args:
        is_active: Whether the user account is active.
        role_code: RBAC role code.
        password_hash: Stored bcrypt hash (real or sentinel value).

    Returns:
        MagicMock configured to satisfy the ``UserRecord`` Protocol.
    """
    user = MagicMock()
    user.id = _TEST_USER_ID
    user.username = "testuser"
    user.password_hash = password_hash
    user.tenant_id = _TEST_TENANT_ID
    user.is_active = is_active
    # Property accessed as attribute in auth_service
    type(user).role_code = property(lambda self: role_code)
    return user


async def _lookup_returns(record: Any):  # type: ignore[misc]
    """Async callable that always returns *record*.

    Args:
        record: The value to return (UserRecord or None).

    Returns:
        Async function that returns *record* regardless of arguments.
    """
    async def _inner(username: str) -> Any:
        return record
    return _inner


# ---------------------------------------------------------------------------
# authenticate_user — happy path
# ---------------------------------------------------------------------------


class TestAuthenticateUserHappyPath:
    """Tests for authenticate_user when credentials are valid."""

    @pytest.mark.asyncio
    async def test_returns_token_response_on_valid_credentials(self) -> None:
        """Known username + correct password → returns TokenResponse."""
        user = _make_user_record()

        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
            return_value=True,
        ):
            result = await authenticate_user(
                username="testuser",
                password="correct_password",
                lookup_user=await _lookup_returns(user),
                correlation_id="test-corr-id",
            )

        assert result is not None
        assert isinstance(result, TokenResponse)
        assert result.token_type == "bearer"
        assert result.access_token != ""
        assert result.refresh_token != ""
        assert result.expires_in > 0

    @pytest.mark.asyncio
    async def test_access_token_contains_correct_claims(self) -> None:
        """Access token sub, role, and tenant_id match the user record."""
        user = _make_user_record(role_code="esg_manager")

        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
            return_value=True,
        ):
            result = await authenticate_user(
                username="testuser",
                password="correct_password",
                lookup_user=await _lookup_returns(user),
            )

        assert result is not None
        claims = decode_token(result.access_token)
        assert claims["sub"] == _TEST_USER_ID
        assert claims["role"] == "esg_manager"
        assert claims["tenant_id"] == _TEST_TENANT_ID
        assert claims["token_type"] == "access"

    @pytest.mark.asyncio
    async def test_refresh_token_claims_are_correct(self) -> None:
        """Refresh token has token_type='refresh' and correct sub."""
        user = _make_user_record()

        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
            return_value=True,
        ):
            result = await authenticate_user(
                username="testuser",
                password="correct_password",
                lookup_user=await _lookup_returns(user),
            )

        assert result is not None
        claims = decode_token(result.refresh_token)
        assert claims["sub"] == _TEST_USER_ID
        assert claims["token_type"] == "refresh"

    @pytest.mark.asyncio
    async def test_verify_password_called_with_correct_args(self) -> None:
        """verify_password is called with the plaintext and stored hash."""
        user = _make_user_record(password_hash="stored_bcrypt_hash")

        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
            return_value=True,
        ) as mock_verify:
            await authenticate_user(
                username="testuser",
                password="raw_plain_password",
                lookup_user=await _lookup_returns(user),
            )

        mock_verify.assert_called_once_with("raw_plain_password", "stored_bcrypt_hash")


# ---------------------------------------------------------------------------
# authenticate_user — failure paths
# ---------------------------------------------------------------------------


class TestAuthenticateUserFailurePaths:
    """Tests for authenticate_user when credentials are invalid or user missing."""

    @pytest.mark.asyncio
    async def test_unknown_username_returns_none(self) -> None:
        """Unknown username (lookup returns None) → authenticate_user returns None."""
        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
        ) as mock_verify:
            result = await authenticate_user(
                username="no_such_user",
                password="any_password",
                lookup_user=await _lookup_returns(None),
                correlation_id="test-corr",
            )

        assert result is None
        # verify_password must NOT be called when the user does not exist;
        # the function short-circuits to avoid leaking user existence via timing.
        # NOTE: auth_service.py short-circuits before verify_password for user-not-found.
        # This is documented behaviour; no dummy-hash call is present in the current
        # implementation.  Test documents the actual behaviour.
        mock_verify.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_password_returns_none(self) -> None:
        """Known username + wrong password → returns None; verify_password called."""
        user = _make_user_record()

        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
            return_value=False,
        ) as mock_verify:
            result = await authenticate_user(
                username="testuser",
                password="wrong_password",
                lookup_user=await _lookup_returns(user),
            )

        assert result is None
        mock_verify.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_password_called_even_on_wrong_password(self) -> None:
        """verify_password receives the submitted password and the stored hash."""
        user = _make_user_record(password_hash="correct_bcrypt_hash")

        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
            return_value=False,
        ) as mock_verify:
            await authenticate_user(
                username="testuser",
                password="wrong_password",
                lookup_user=await _lookup_returns(user),
            )

        mock_verify.assert_called_once_with("wrong_password", "correct_bcrypt_hash")

    @pytest.mark.asyncio
    async def test_inactive_user_returns_none(self) -> None:
        """Disabled user (is_active=False) → returns None; verify_password NOT called."""
        user = _make_user_record(is_active=False)

        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
        ) as mock_verify:
            result = await authenticate_user(
                username="testuser",
                password="any_password",
                lookup_user=await _lookup_returns(user),
            )

        assert result is None
        # auth_service short-circuits before password check for inactive users
        mock_verify.assert_not_called()

    @pytest.mark.asyncio
    async def test_inactive_user_check_happens_before_password_verify(self) -> None:
        """is_active=False is checked before verify_password to avoid leaking state."""
        user = _make_user_record(is_active=False, password_hash="some_hash")

        call_log: list[str] = []

        async def lookup(username: str) -> MagicMock:
            call_log.append("lookup")
            return user

        def fake_verify(plain: str, hashed: str) -> bool:
            call_log.append("verify")
            return True

        with patch(
            "ghg_tool.application.services.auth_service.verify_password",
            side_effect=fake_verify,
        ):
            result = await authenticate_user(
                username="testuser",
                password="pw",
                lookup_user=lookup,
            )

        assert result is None
        assert "lookup" in call_log
        assert "verify" not in call_log


# ---------------------------------------------------------------------------
# refresh_access_token — happy path
# ---------------------------------------------------------------------------


class TestRefreshAccessTokenHappyPath:
    """Tests for refresh_access_token when the refresh token is valid."""

    def test_returns_token_response_on_valid_refresh_token(self) -> None:
        """Valid refresh token → new TokenResponse returned."""
        sub = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        refresh_tok = create_refresh_token(sub=sub, tenant_id=tenant_id)

        result = refresh_access_token(
            refresh_tok,
            role="data_steward",
            correlation_id="test-corr",
        )

        assert result is not None
        assert isinstance(result, TokenResponse)
        assert result.token_type == "bearer"
        assert result.access_token != ""
        assert result.expires_in > 0

    def test_new_access_token_contains_updated_role(self) -> None:
        """New access token carries the role supplied to refresh_access_token."""
        sub = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        refresh_tok = create_refresh_token(sub=sub, tenant_id=tenant_id)

        result = refresh_access_token(refresh_tok, role="esg_manager")

        assert result is not None
        claims = decode_token(result.access_token)
        assert claims["role"] == "esg_manager"
        assert claims["sub"] == sub
        assert claims["token_type"] == "access"

    def test_new_access_token_sub_matches_refresh_token_sub(self) -> None:
        """New access token sub matches the refresh token's sub claim."""
        sub = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        refresh_tok = create_refresh_token(sub=sub, tenant_id=tenant_id)

        result = refresh_access_token(refresh_tok, role="auditor")

        assert result is not None
        claims = decode_token(result.access_token)
        assert claims["sub"] == sub

    def test_refresh_token_unchanged_in_v1(self) -> None:
        """In v1, the refresh token in the response is unchanged (not rotated)."""
        sub = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        refresh_tok = create_refresh_token(sub=sub, tenant_id=tenant_id)

        result = refresh_access_token(refresh_tok, role="data_steward")

        assert result is not None
        assert result.refresh_token == refresh_tok


# ---------------------------------------------------------------------------
# refresh_access_token — failure paths
# ---------------------------------------------------------------------------


class TestRefreshAccessTokenFailurePaths:
    """Tests for refresh_access_token when the token is invalid, expired, or wrong type."""

    def test_malformed_token_returns_none(self) -> None:
        """A completely malformed token string → returns None (no raise)."""
        result = refresh_access_token("not.a.valid.jwt", role="data_steward")
        assert result is None

    def test_garbage_string_returns_none(self) -> None:
        """Arbitrary garbage → returns None."""
        result = refresh_access_token("garbage_input_xyz_123", role="data_steward")
        assert result is None

    def test_expired_refresh_token_returns_none(self) -> None:
        """Expired refresh token → returns None (ExpiredSignatureError caught internally)."""
        expired_token = jose_jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "tenant_id": str(uuid.uuid4()),
                "jti": str(uuid.uuid4()),
                "iat": int(time.time()) - 200,
                "exp": int(time.time()) - 100,  # expired 100 s ago
                "token_type": "refresh",
            },
            _TEST_SECRET,
            algorithm="HS256",
        )
        result = refresh_access_token(expired_token, role="data_steward")
        assert result is None

    def test_access_token_passed_as_refresh_returns_none(self) -> None:
        """An access token (token_type='access') used as refresh → returns None.

        This validates the token_type guard in refresh_access_token (line 134
        of auth_service.py: ``if claims.get("token_type") != "refresh"``).
        """
        access_tok = jose_jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "role": "data_steward",
                "tenant_id": str(uuid.uuid4()),
                "jti": str(uuid.uuid4()),
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
                "token_type": "access",  # wrong type — must be rejected
            },
            _TEST_SECRET,
            algorithm="HS256",
        )
        result = refresh_access_token(access_tok, role="data_steward")
        assert result is None

    def test_wrong_signing_key_returns_none(self) -> None:
        """Token signed with a different key → returns None (JWTError caught)."""
        token_wrong_key = jose_jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "tenant_id": str(uuid.uuid4()),
                "jti": str(uuid.uuid4()),
                "iat": int(time.time()),
                "exp": int(time.time()) + 86400,
                "token_type": "refresh",
            },
            "completely-different-secret-key-xyz",
            algorithm="HS256",
        )
        result = refresh_access_token(token_wrong_key, role="data_steward")
        assert result is None

    def test_token_with_no_token_type_claim_returns_none(self) -> None:
        """Token missing the token_type claim → returns None (type mismatch guard)."""
        token_no_type = jose_jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "tenant_id": str(uuid.uuid4()),
                "jti": str(uuid.uuid4()),
                "iat": int(time.time()),
                "exp": int(time.time()) + 86400,
                # token_type deliberately omitted
            },
            _TEST_SECRET,
            algorithm="HS256",
        )
        result = refresh_access_token(token_no_type, role="data_steward")
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string → returns None without raising."""
        result = refresh_access_token("", role="data_steward")
        assert result is None
