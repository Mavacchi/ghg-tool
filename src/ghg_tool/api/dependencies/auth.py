"""JWT authentication dependency — SG-01, NFR-05.

Extracts the ``Authorization: Bearer <token>`` header, decodes and validates
the JWT, and returns a ``CurrentUser`` Pydantic model for injection into route
handlers.  Raises 401 for all auth failures and 403 for RBAC failures
(handled in the RBAC middleware layer).
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import ExpiredSignatureError, JWTError
from pydantic import BaseModel, ConfigDict, Field

from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.infrastructure.security import jwt as jwt_module

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

RoleCode = Literal["data_steward", "esg_manager", "auditor"]


class CurrentUser(BaseModel):
    """Decoded JWT claims for the authenticated request user.

    Attributes:
        sub: Subject claim — user UUID string.
        role: RBAC role code.
        tenant_id: Tenant UUID string for RLS GUC injection.
        jti: JWT ID — used for token blacklist checks (v2).
    """

    model_config = ConfigDict(frozen=True)

    sub: str = Field(min_length=1)
    role: RoleCode
    tenant_id: str = Field(min_length=1)
    jti: str = Field(default="")


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
    except ExpiredSignatureError:
        log.warning("JWT token expired", jti=_safe_jti(token))
        raise _unauthorized("Token has expired")
    except ValueError as exc:
        log.warning("Forbidden JWT algorithm", detail=str(exc))
        raise _unauthorized(str(exc))
    except JWTError as exc:
        log.warning("JWT validation failed", detail=str(exc))
        raise _unauthorized("Invalid token")

    role = claims.get("role", "")
    if role not in {"data_steward", "esg_manager", "auditor"}:
        log.warning("JWT contains unknown role", role=role)
        raise _unauthorized(f"Unknown role in token: {role!r}")

    user = CurrentUser(
        sub=claims.get("sub", ""),
        role=role,  # type: ignore[arg-type]
        tenant_id=claims.get("tenant_id", ""),
        jti=claims.get("jti", ""),
    )

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
