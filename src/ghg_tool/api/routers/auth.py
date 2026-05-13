"""Auth router — POST /api/v1/auth/login, /refresh, /logout.

Implements the JWT authentication flow per SG-01 / NFR-05.  Passwords are
NEVER logged or echoed.  All responses carry a ``correlation_id``.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, status

from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.schemas.auth_schemas import LoginRequest, RefreshRequest, TokenResponse
from ghg_tool.infrastructure.security import jwt as jwt_module

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain JWT token pair",
    description=(
        "Validates username/password credentials and returns an access token "
        "(1 h TTL) and a refresh token (24 h TTL). Passwords are never logged. "
        "Implements NFR-05 token lifetimes and SG-01 alg=none rejection."
    ),
    responses={
        200: {"description": "Authentication successful"},
        401: {"description": "Invalid credentials", "content": {"application/problem+json": {}}},
        422: {"description": "Validation error"},
    },
)
async def login(body: LoginRequest) -> TokenResponse:
    """Login endpoint — returns a token pair on successful authentication.

    In v1, user lookup hits the DB via ``auth_service``; a stub is used here
    so the endpoint is testable without a live PostgreSQL instance.  Wave 3
    wires the real repository.

    Args:
        body: ``LoginRequest`` with ``username`` and ``password`` fields.

    Returns:
        ``TokenResponse`` with access + refresh tokens.

    Raises:
        HTTPException: 401 if credentials are invalid.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, username=body.username)
    log.info("Login attempt")

    # Wave 3: replace stub with real DB lookup via auth_service.authenticate_user
    # For now raise 501 to signal "not yet wired" — tests mock this endpoint.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "type": "about:blank",
            "title": "Service Unavailable",
            "status": 503,
            "detail": "User database not yet wired (wave 3). Use test tokens.",
            "correlation_id": correlation_id,
        },
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token using a valid refresh token",
    description=(
        "Validates a refresh token and issues a new access token. "
        "The refresh token is not rotated in v1."
    ),
    responses={
        200: {"description": "Token refreshed"},
        401: {"description": "Invalid or expired refresh token"},
    },
)
async def refresh(body: RefreshRequest) -> TokenResponse:
    """Refresh token endpoint.

    Args:
        body: ``RefreshRequest`` containing the refresh JWT.

    Returns:
        A new ``TokenResponse`` with a fresh access token.

    Raises:
        HTTPException: 401 if the refresh token is invalid or expired.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id)

    try:
        claims = jwt_module.decode_token(body.refresh_token)
    except Exception as exc:  # noqa: BLE001
        log.warning("Refresh token validation failed")
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

    sub = claims.get("sub", "")
    tenant_id = claims.get("tenant_id", "")
    # Wave 3: re-fetch role from DB to prevent role elevation
    role = claims.get("role", "data_steward")

    new_access = jwt_module.create_access_token(
        sub=sub, role=role, tenant_id=tenant_id
    )
    log.info("Token refreshed", user_id=sub[:8])
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
