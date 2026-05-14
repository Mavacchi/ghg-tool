"""Auth router — POST /api/v1/auth/login, /refresh, /logout.

Implements the JWT authentication flow per SG-01 / NFR-05.  Passwords are
NEVER logged or echoed.  All responses carry a ``correlation_id``.

SEC-P0-004: The refresh endpoint re-fetches the role from ``ref.users``
joined to ``ref.roles`` after validating the refresh token, preventing
silent privilege elevation via stale or cross-role refresh tokens.

SEC-P0-005: Usernames are never emitted in plain text.  A 16-char
SHA-256 prefix is used for SIEM correlation without PII leakage.

SEC-P1-003: The login endpoint is decorated with a 5/minute per-IP
rate limit to mitigate credential stuffing.

SEC-P1-005: The login route is wired to ``authenticate_user`` with a
real DB lookup replacing the previous 503 stub.
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.db import get_db_no_auth
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rate_limit import login_limiter
from ghg_tool.api.schemas.auth_schemas import LoginRequest, RefreshRequest, TokenResponse
from ghg_tool.application.services.auth_service import authenticate_user
from ghg_tool.infrastructure.security import jwt as jwt_module

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _hash_username(username: str) -> str:
    """Return 16-char SHA-256 prefix for SIEM correlation without PII leakage."""
    return hashlib.sha256(username.encode("utf-8")).hexdigest()[:16]


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain JWT token pair",
    description=(
        "Validates username/password credentials and returns an access token "
        "(1 h TTL) and a refresh token (24 h TTL). Passwords are never logged. "
        "Implements NFR-05 token lifetimes and SG-01 alg=none rejection. "
        "SEC-P1-003: limited to 5 requests per minute per IP to mitigate "
        "credential stuffing. SEC-P1-005: wired to the real DB lookup."
    ),
    responses={
        200: {"description": "Authentication successful"},
        401: {"description": "Invalid credentials", "content": {"application/problem+json": {}}},
        429: {"description": "Rate limit exceeded"},
        422: {"description": "Validation error"},
    },
)
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_no_auth),
) -> TokenResponse:
    """Login endpoint — wired to ``authenticate_user`` with DB lookup.

    SEC-P0-005: username is never logged in plain text; a 16-char SHA-256
    prefix is used for SIEM correlation.
    SEC-P1-003: rate-limited to 5 requests per minute per source IP.
    SEC-P1-005: replaces the previous 503 stub with a real DB lookup.

    Args:
        request: The HTTP request (used for rate-limit key extraction).
        body: ``LoginRequest`` with ``username`` and ``password`` fields.
        session: Async DB session for user lookup.

    Returns:
        ``TokenResponse`` with access + refresh tokens.

    Raises:
        HTTPException: 401 if credentials are invalid or rate limit exceeded.
    """
    # SEC-P1-003: check per-IP rate limit for login endpoint
    client_ip = request.client.host if request.client else "unknown"
    if not login_limiter.is_allowed(f"login:ip:{client_ip}"):
        correlation_id = get_correlation_id()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "type": "about:blank",
                "title": "Too Many Requests",
                "status": 429,
                "detail": "Login rate limit exceeded: 5 attempts per minute.",
                "correlation_id": correlation_id,
            },
        )

    correlation_id = get_correlation_id()
    # SEC-P0-005: never log plain username — use 16-char SHA-256 prefix
    log = logger.bind(
        correlation_id=correlation_id,
        username_hash=_hash_username(body.username),  # 16-char SHA-256 prefix, no PII
    )
    log.info("login_attempt")

    async def _lookup(username: str) -> Any:
        result = await session.execute(
            text(
                "SELECT u.id, u.username, u.password_hash, u.is_active, "
                "r.role_code, u.tenant_id "
                "FROM ref.users u "
                "JOIN ref.roles r ON r.id = u.role_id "
                "WHERE u.username = :username"
            ),
            {"username": username},
        )
        return result.fetchone()

    token_response = await authenticate_user(
        username=body.username,
        password=body.password,
        lookup_user=_lookup,
        correlation_id=correlation_id,
    )
    if token_response is None:
        log.warning("login_failed", probe_attempt=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Invalid credentials",
                "correlation_id": correlation_id,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    log.info("login_successful")
    return token_response


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token using a valid refresh token",
    description=(
        "Validates a refresh token and issues a new access token. "
        "The refresh token is not rotated in v1. "
        "SEC-P0-004: the role is re-fetched from the database on every "
        "refresh to prevent silent privilege elevation via stale tokens."
    ),
    responses={
        200: {"description": "Token refreshed"},
        401: {"description": "Invalid or expired refresh token"},
    },
)
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_no_auth),
) -> TokenResponse:
    """Refresh token endpoint.

    SEC-P0-004: role is always re-fetched from ``ref.users JOIN ref.roles``
    using the ``sub`` claim.  The refresh token never carries a ``role``
    claim (see ``create_refresh_token``), so the previous
    ``claims.get("role", "data_steward")`` default was a silent privilege
    elevation vector — any role could be obtained by calling /refresh.

    SEC-P1-006: all ``log.warning`` calls in this handler include
    ``probe_attempt=True`` so SIEM filters can aggregate suspicious refresh
    patterns.

    Args:
        body: ``RefreshRequest`` containing the refresh JWT.
        session: Async DB session for re-fetching the user's current role.

    Returns:
        A new ``TokenResponse`` with a fresh access token.

    Raises:
        HTTPException: 401 if the refresh token is invalid, expired, or
            the user no longer exists / is inactive.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id)

    try:
        claims = jwt_module.decode_token(body.refresh_token)
    except Exception as exc:  # noqa: BLE001
        log.warning("refresh_token_validation_failed", probe_attempt=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Refresh token is invalid or expired",
                "correlation_id": correlation_id,
            },
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if claims.get("token_type") != "refresh":
        log.warning("refresh_token_type_mismatch", probe_attempt=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Provided token is not a refresh token",
                "correlation_id": correlation_id,
            },
        )

    user_id = claims.get("sub", "")
    tenant_id = claims.get("tenant_id", "")

    # SEC-P0-004: re-fetch role from DB to prevent silent privilege elevation.
    # The refresh token intentionally carries no "role" claim; the authoritative
    # role must come from ref.users JOIN ref.roles on every refresh.
    user_row = await session.execute(
        text(
            "SELECT u.id, u.username, r.role_code, u.is_active "
            "FROM ref.users u "
            "JOIN ref.roles r ON r.id = u.role_id "
            "WHERE u.id = :uid::uuid"
        ),
        {"uid": user_id},
    )
    row = user_row.fetchone()
    if row is None or not row.is_active:
        log.warning(
            "refresh_failed_user_not_found_or_inactive",
            user_id=user_id[:8],
            probe_attempt=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": "Invalid refresh token",
                "correlation_id": correlation_id,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    role: str = row.role_code
    new_access = jwt_module.create_access_token(
        sub=user_id, role=role, tenant_id=tenant_id
    )
    log.info("token_refreshed", user_id=user_id[:8])
    return TokenResponse(
        access_token=new_access,
        refresh_token=body.refresh_token,
        expires_in=jwt_module.ACCESS_TOKEN_TTL_S,
        token_type="bearer",
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Logout (optional token blacklist placeholder)",
    description=(
        "In v1, logout is a no-op that returns 204. Token blacklisting via Redis "
        "is deferred to v2. Clients should discard the token locally on logout."
    ),
    responses={204: {"description": "Logged out"}},
)
async def logout() -> None:
    """Logout endpoint — v1 no-op placeholder.

    Returns:
        None (204 No Content).
    """
    logger.bind(correlation_id=get_correlation_id()).info("Logout called (v1 no-op)")
