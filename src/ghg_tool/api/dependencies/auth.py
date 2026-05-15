"""JWT authentication dependency — SG-01, NFR-05.

Extracts the ``Authorization: Bearer <token>`` header, decodes and validates
the JWT, and returns a ``CurrentUser`` Pydantic model for injection into route
handlers.  Raises 401 for all auth failures and 403 for RBAC failures
(handled in the RBAC middleware layer).
"""

from __future__ import annotations

import uuid
from typing import Literal

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import ExpiredSignatureError, JWTError  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.infrastructure.security import jwt as jwt_module

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

RoleCode = Literal["editor", "admin", "viewer"]


class CurrentUser(BaseModel):
    """Decoded JWT claims for the authenticated request user.

    Attributes:
        sub: Subject claim -- user UUID string.
        role: RBAC role code.
        tenant_id: Tenant UUID string for RLS GUC injection.
        jti: JWT ID -- used for token blacklist / session checks.
        pre_2fa: If True the token is a partial pre-TOTP token and MUST NOT
            be accepted as a Bearer credential on any protected endpoint.
    """

    model_config = ConfigDict(frozen=True)

    sub: str = Field(min_length=1)
    role: RoleCode
    tenant_id: str = Field(min_length=1)
    jti: str = Field(default="")
    pre_2fa: bool = Field(default=False)

    @field_validator("sub")
    @classmethod
    def _validate_sub_uuid(cls, value: str) -> str:
        """Reject non-UUID subject claims.

        Documented invariant: the JWT ``sub`` claim is a user UUID, never
        an email (avoids PII in logs). Enforce it at the Pydantic boundary
        so a future identity-provider misconfiguration that injects an
        email surfaces as a 401 at the auth gate rather than leaking PII
        into every structured log line that binds ``user.sub`` or
        ``published_by``.
        """
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("sub must be a valid UUID") from exc
        return value

    @field_validator("tenant_id")
    @classmethod
    def _validate_tenant_uuid(cls, value: str) -> str:
        """Reject non-UUID tenant claims so callers can pass tenant_id to
        ``uuid.UUID()`` without a 500 leak. Bad JWTs surface as 401 from the
        get_current_user dependency instead."""
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("tenant_id must be a valid UUID") from exc
        return value


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """FastAPI dependency: decode JWT and return the current user.

    Sets ``request.state.user_sub`` for rate-limit key extraction.

    Args:
        request: The incoming HTTP request (for setting state).
        credentials: The parsed ``Authorization: Bearer`` header.

    Returns:
        The ``CurrentUser`` built from validated JWT claims.

    Raises:
        HTTPException: 401 if token is absent, expired, or invalid.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id)

    if credentials is None:
        log.warning("Missing Authorization header")
        raise _unauthorized("Missing or malformed Authorization header")

    token = credentials.credentials
    try:
        claims = jwt_module.decode_token(token)
    except ExpiredSignatureError as exc:
        log.warning("JWT token expired", jti=_safe_jti(token))
        raise _unauthorized("Token has expired") from exc
    except ValueError as exc:
        log.warning("Forbidden JWT algorithm", detail=str(exc))
        raise _unauthorized(str(exc)) from exc
    except JWTError as exc:
        log.warning("JWT validation failed", detail=str(exc))
        raise _unauthorized("Invalid token") from exc

    role = claims.get("role", "")
    if role not in {"editor", "admin", "viewer"}:
        log.warning("JWT contains unknown role", role=role)
        raise _unauthorized(f"Unknown role in token: {role!r}")

    pre_2fa: bool = bool(claims.get("pre_2fa", False))
    if pre_2fa:
        log.warning("pre_2fa token rejected on protected endpoint", probe_attempt=True)
        raise _unauthorized(
            "Partial 2FA token cannot be used as Bearer. Complete TOTP challenge first."
        )

    try:
        user = CurrentUser(
            sub=claims.get("sub", ""),
            role=role,  # noqa: PGH003  # narrowed by guard above; mypy can't track dict lookup
            tenant_id=claims.get("tenant_id", ""),
            jti=claims.get("jti", ""),
            pre_2fa=False,
        )
    except ValueError as exc:
        # Pydantic validation failure (e.g. non-UUID tenant_id) -- surface as
        # 401 rather than letting the resulting ValueError bubble to a 500.
        log.warning("JWT claim validation failed", detail=str(exc))
        raise _unauthorized("Invalid token claims") from exc

    # Store sub on request.state for rate-limit middleware
    request.state.user_sub = user.sub

    return user


def _unauthorized(detail: str) -> HTTPException:
    """Build a 401 HTTPException with RFC 7807 problem body.

    Args:
        detail: Human-readable error detail.

    Returns:
        A 401 HTTPException.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "type": "about:blank",
            "title": "Unauthorized",
            "status": 401,
            "detail": detail,
            "correlation_id": get_correlation_id(),
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def _safe_jti(token: str) -> str:
    """Return the first 8 characters of the token for safe logging.

    Never logs the full token (NFR-08, SG-07).

    Args:
        token: Raw JWT string.

    Returns:
        First 8 characters of the token string (truncated, not decodable).
    """
    return token[:8] if token else ""
