"""Authentication service — handles login, refresh, and token issuance.

This service is the application-layer orchestrator for the auth flow.  It
calls the infrastructure password hasher and JWT encoder; it does NOT
implement the cryptographic primitives itself.

Database access is optional in tests — the service accepts a repository-style
callable for user lookup to support dependency injection.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog
from jose import JWTError  # type: ignore[import-untyped]
from jose.exceptions import ExpiredSignatureError  # type: ignore[import-untyped]

from ghg_tool.api.schemas.auth_schemas import TokenResponse
from ghg_tool.infrastructure.security import jwt as jwt_module
from ghg_tool.infrastructure.security.password import verify_password

logger = structlog.get_logger(__name__)


class UserRecord(Protocol):
    """Minimal protocol for a user ORM row used by auth_service.

    Only the fields required for authentication are declared; the actual
    SQLAlchemy model ``User`` satisfies this protocol.
    """

    id: Any
    username: str
    password_hash: str
    tenant_id: Any
    is_active: bool

    @property
    def role_code(self) -> str:
        """The RBAC role code string for this user."""
        ...


async def authenticate_user(
    username: str,
    password: str,
    *,
    lookup_user: Callable[[str], Awaitable[UserRecord | None]],
    correlation_id: str = "",
) -> TokenResponse | None:
    """Verify credentials and return token pair or None on failure.

    Uses constant-time comparison (``passlib.verify``) to prevent timing
    attacks on the password check.  Returns ``None`` on failure rather than
    raising, so the caller controls the 401 response shape.

    Passwords are NEVER logged — only a truncated user_id is emitted.

    Args:
        username: The username provided by the client.
        password: The raw password provided by the client (never logged).
        lookup_user: An awaitable that accepts a username and returns
            a ``UserRecord`` or None.
        correlation_id: Correlation ID for log binding.

    Returns:
        A ``TokenResponse`` on success; ``None`` if credentials are invalid
        or the user is inactive.
    """
    log = logger.bind(correlation_id=correlation_id, username=username)

    user = await lookup_user(username)
    if user is None:
        log.info("Login failed: user not found")
        return None

    if not user.is_active:
        log.info("Login failed: inactive user", user_id=str(user.id)[:8])
        return None

    if not verify_password(password, user.password_hash):
        log.info("Login failed: wrong password", user_id=str(user.id)[:8])
        return None

    log.info("Login successful", user_id=str(user.id)[:8], role=user.role_code)
    access_token = jwt_module.create_access_token(
        sub=str(user.id),
        role=user.role_code,
        tenant_id=str(user.tenant_id),
    )
    refresh_token = jwt_module.create_refresh_token(
        sub=str(user.id),
        tenant_id=str(user.tenant_id),
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=jwt_module.ACCESS_TOKEN_TTL_S,
        token_type="bearer",
    )


def refresh_access_token(
    refresh_token: str,
    *,
    role: str,
    correlation_id: str = "",
) -> TokenResponse | None:
    """Issue a new access token from a valid refresh token.

    Validates the refresh token (expiry, algorithm, token_type claim) and
    issues a new access token.  The refresh token is NOT rotated in v1 to
    keep the flow simple; rotation can be added in v2.

    Args:
        refresh_token: The raw refresh JWT from the client.
        role: The role to embed in the new access token (must be re-fetched
            from DB to prevent role elevation via stale refresh tokens).
        correlation_id: Correlation ID for log binding.

    Returns:
        A ``TokenResponse`` on success; ``None`` if the refresh token is
        invalid or expired.
    """
    log = logger.bind(correlation_id=correlation_id)
    try:
        claims = jwt_module.decode_token(refresh_token)
    except (JWTError, ExpiredSignatureError, ValueError) as exc:
        log.warning("Refresh token validation failed", exc_type=type(exc).__name__)
        return None

    if claims.get("token_type") != "refresh":
        log.warning("Token type mismatch on refresh")
        return None

    sub = claims.get("sub", "")
    tenant_id = claims.get("tenant_id", "")
    new_access = jwt_module.create_access_token(
        sub=sub, role=role, tenant_id=tenant_id
    )
    log.info("Access token refreshed", user_id=sub[:8])
    return TokenResponse(
        access_token=new_access,
        refresh_token=refresh_token,  # unchanged in v1
        expires_in=jwt_module.ACCESS_TOKEN_TTL_S,
        token_type="bearer",
    )
