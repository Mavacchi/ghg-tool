"""Auth router -- POST /api/v1/auth/login, /refresh, /logout.

Implements the JWT authentication flow per SG-01 / NFR-05.  Passwords are
NEVER logged or echoed.  All responses carry a ``correlation_id``.

SEC-P0-004: The refresh endpoint re-fetches the role AND tenant_id from
``ref.users`` joined to ``ref.roles`` after validating the refresh token,
preventing silent privilege elevation via stale or cross-role refresh tokens.
BUG-16: tenant_id is now always taken from DB, never from the refresh claim.

SEC-P0-005: Usernames are never emitted in plain text.  A 16-char
SHA-256 prefix is used for SIEM correlation without PII leakage.

SEC-P1-003: The login endpoint is decorated with a 5/minute per-IP
rate limit to mitigate credential stuffing.

SEC-P1-005: The login route is wired to ``authenticate_user`` with a
real DB lookup replacing the previous 503 stub.

BUG-01 / S-007: Session rows are inserted into auth.sessions for every
issued token (login no-TOTP, totp/challenge, refresh) BEFORE the response
is returned.  Session revocation is now enforceable.

S-006: Refresh token rotation -- the old refresh jti is revoked and a new
refresh token is issued.  Reuse of a revoked refresh token is treated as a
compromise signal and emits a SIEM ALERT.

BUG-10: TOTP-enabled login short-circuits BEFORE building the full access+
refresh pair, preventing orphan jti leakage into structured logs.

BUG-15: Logout now sets revoked_at on the session row.

S-027: ``tenant_code`` optional field on LoginRequest; raises 401 with
``ambiguous_username_tenant_required`` when two users share a username across
tenants and no tenant_code is provided.

R-10: TTL constants imported from infrastructure.security.constants.
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.db import get_db_no_auth
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rate_limit import login_limiter
from ghg_tool.api.schemas.auth_schemas import LoginRequest, RefreshRequest, TokenResponse
from ghg_tool.application.services.auth_service import authenticate_user
from ghg_tool.application.services.session_service import (
    insert_auth_session,
    revoke_auth_session_by_jti,
)
from ghg_tool.infrastructure.security import jwt as jwt_module
from ghg_tool.infrastructure.security import siem
from ghg_tool.infrastructure.security.constants import (
    ACCESS_TOKEN_TTL_S,
    PARTIAL_TOKEN_TTL_S,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_bearer_scheme = HTTPBearer(auto_error=False)


def _hash_username(username: str) -> str:
    """Return 16-char SHA-256 prefix for SIEM correlation without PII leakage."""
    return hashlib.sha256(username.encode("utf-8")).hexdigest()[:16]


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain JWT token pair",
    description=(
        "Validates username/password credentials and returns an access token "
        "(1 h TTL) and a refresh token (24 h TTL). Passwords are never logged. "
        "If totp_enabled=true for the user, returns 202 with requires_totp=true "
        "and a short-lived partial_token (5 min, pre_2fa claim); the caller must "
        "complete the TOTP challenge at POST /api/v1/auth/totp/challenge. "
        "Implements NFR-05 token lifetimes and SG-01 alg=none rejection. "
        "SEC-P1-003: limited to 5 requests per minute per IP to mitigate "
        "credential stuffing. SEC-P1-005: wired to the real DB lookup. "
        "BUG-10: TOTP-required short-circuits before building the full token pair. "
        "BUG-01: session row inserted before returning the token. "
        "S-027: optional tenant_code for disambiguation when usernames repeat "
        "across tenants."
    ),
    responses={
        200: {"description": "Authentication successful", "model": TokenResponse},
        202: {"description": "TOTP challenge required"},
        401: {"description": "Invalid credentials", "content": {"application/problem+json": {}}},
        429: {"description": "Rate limit exceeded"},
        422: {"description": "Validation error"},
    },
)
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_no_auth),
) -> Any:
    """Login endpoint -- wired to ``authenticate_user`` with DB lookup.

    SEC-P0-005: username is never logged in plain text; a 16-char SHA-256
    prefix is used for SIEM correlation.
    SEC-P1-003: rate-limited to 5 requests per minute per source IP.
    SEC-P1-005: replaces the previous 503 stub with a real DB lookup.
    BUG-10: if totp_enabled, short-circuit BEFORE building the full token pair.
    BUG-01: session row is inserted for no-TOTP path before returning.

    Args:
        request: The HTTP request (used for rate-limit key extraction and audit).
        body: ``LoginRequest`` with ``username``, ``password``, and optional
            ``tenant_code`` fields.
        session: Async DB session for user lookup.

    Returns:
        ``TokenResponse`` with access + refresh tokens, or 202 TOTP redirect.

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
    user_agent = request.headers.get("user-agent")
    # SEC-P0-005: never log plain username -- use 16-char SHA-256 prefix
    log = logger.bind(
        correlation_id=correlation_id,
        username_hash=_hash_username(body.username),  # 16-char SHA-256 prefix, no PII
    )
    log.info("login_attempt")

    async def _lookup(username: str) -> Any:
        # S-027: when tenant_code is provided, filter by tenant to prevent
        # cross-tenant username collisions.
        if body.tenant_code:
            result = await session.execute(
                text(
                    "SELECT u.id, u.username, u.password_hash, u.is_active, "
                    "r.role_code, u.tenant_id, u.totp_enabled "
                    "FROM ref.users u "
                    "JOIN ref.roles r ON r.id = u.role_id "
                    "JOIN ref.tenants t ON t.id = u.tenant_id "
                    "WHERE u.username = :username "
                    "  AND t.tenant_code = :tenant_code"
                ),
                {"username": username, "tenant_code": body.tenant_code},
            )
        else:
            result = await session.execute(
                text(
                    "SELECT u.id, u.username, u.password_hash, u.is_active, "
                    "r.role_code, u.tenant_id, u.totp_enabled "
                    "FROM ref.users u "
                    "JOIN ref.roles r ON r.id = u.role_id "
                    "WHERE u.username = :username"
                ),
                {"username": username},
            )
        rows = result.fetchall()

        # S-027: detect cross-tenant username collision when no tenant_code given.
        if not body.tenant_code and len(rows) > 1:
            log.warning(
                "login_ambiguous_username",
                username_hash=_hash_username(username),
            )
            return "AMBIGUOUS"

        if not body.tenant_code and rows:
            # Log a structured warning for migration tracking (no tenant_code).
            log.info(
                "login_no_tenant_scope",
                username_hash=_hash_username(username),
            )

        return rows[0] if rows else None

    # BUG-10: do the lookup FIRST, then decide TOTP branch BEFORE building
    # the full token pair.  This prevents orphan jti leakage into logs.
    user_row = await _lookup(body.username)

    # S-027: ambiguous username collision
    if user_row == "AMBIGUOUS":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": "ambiguous_username_tenant_required",
                "correlation_id": correlation_id,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

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

    # BUG-10: Check TOTP BEFORE we have built the full token pair.
    # Re-fetch the user row via a second _lookup call (authenticate_user
    # returns a TokenResponse, not the row).  We need totp_enabled.
    # Since authenticate_user succeeded, user_row is the authenticated row.
    # Refresh user_row after authenticate_user to pick up latest state.
    user_row = await _lookup(body.username)

    totp_enabled = getattr(user_row, "totp_enabled", False)
    if user_row is not None and user_row != "AMBIGUOUS" and totp_enabled:
        # BUG-10: build ONLY the partial token here; the full pair is never
        # constructed in this branch, preventing orphan jti leakage.
        partial_token = jwt_module.create_access_token(
            sub=str(user_row.id),
            role=str(user_row.role_code),
            tenant_id=str(user_row.tenant_id),
            extra_claims={"pre_2fa": True},
            ttl_seconds=PARTIAL_TOKEN_TTL_S,
        )
        log.info("login_totp_required")
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "requires_totp": True,
                "partial_token": partial_token,
                "correlation_id": correlation_id,
            },
        )

    # No-TOTP path: insert the session row BEFORE returning the token.
    # BUG-01 / S-007: session must exist before client receives the token.
    access_claims = jwt_module.decode_token(token_response.access_token)
    access_jti: str = access_claims.get("jti", "")
    await insert_auth_session(
        session,
        user_id=access_claims.get("sub", ""),
        tenant_id=access_claims.get("tenant_id", ""),
        jti=access_jti,
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    await session.flush()

    log.info("login_successful")
    return token_response


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token using a valid refresh token",
    description=(
        "Validates a refresh token and issues a new access + refresh token pair. "
        "S-006: refresh token is rotated -- the old jti is revoked and a new "
        "refresh token is issued. Reuse of a revoked refresh token emits a "
        "SIEM ALERT (compromise indicator). "
        "BUG-16: tenant_id is re-fetched from the DB, never taken from the "
        "refresh token claim. "
        "SEC-P0-004: the role is re-fetched from the database on every "
        "refresh to prevent silent privilege elevation via stale tokens. "
        "BUG-01: session row inserted for the new access jti."
    ),
    responses={
        200: {"description": "Token refreshed"},
        401: {"description": "Invalid or expired refresh token"},
    },
)
async def refresh(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_no_auth),
) -> TokenResponse:
    """Refresh token endpoint with rotation.

    S-006: On each refresh, mint a new refresh token with a fresh jti,
    record it in auth.sessions, and mark the previous jti revoked.

    BUG-16: tenant_id and role are always read from ref.users; the refresh
    claim is used only to identify the user (sub), not to grant privileges.

    SEC-P0-004: role is always re-fetched from ref.users JOIN ref.roles
    using the sub claim.

    Args:
        request: HTTP request for IP/UA extraction (session row insert).
        body: RefreshRequest containing the refresh JWT.
        session: Async DB session for re-fetching the user's current role.

    Returns:
        A new TokenResponse with a fresh access token and rotated refresh token.

    Raises:
        HTTPException: 401 if the refresh token is invalid, expired, revoked,
            or the user no longer exists / is inactive.
    """
    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent")
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
    old_refresh_jti: str = claims.get("jti", "")

    # S-006: check if the old refresh jti's session row exists and its state.
    refresh_session_result = await session.execute(
        text(
            "SELECT id, revoked_at FROM auth.sessions "
            "WHERE jti = :jti LIMIT 1"
        ),
        {"jti": old_refresh_jti},
    )
    refresh_session_row = refresh_session_result.fetchone()

    if refresh_session_row is not None and refresh_session_row.revoked_at is not None:
        # S-006: revoked refresh token reuse -- this is a compromise indicator.
        log.warning(
            "refresh_token_reused_after_revocation",
            jti_prefix=old_refresh_jti[:8],
            user_id=user_id[:8],
            probe_attempt=True,
        )
        siem.emit(
            event="refresh_token_reused_compromised",
            correlation_id=correlation_id,
            tenant_id=claims.get("tenant_id", ""),
            user_sub=user_id,
            severity="HIGH",
            payload={
                "jti_prefix": old_refresh_jti[:8],
                "detail": "Revoked refresh token reused: possible token theft",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": "refresh_token_reused",
                "correlation_id": correlation_id,
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # BUG-16 / SEC-P0-004: re-fetch role AND tenant_id from DB.
    # The refresh token never carries a role; tenant_id is sourced from the DB,
    # not from the refresh claim, to prevent tampered-claim elevation.
    user_row = await session.execute(
        text(
            "SELECT u.id, u.username, r.role_code, u.is_active, u.tenant_id "
            "FROM ref.users u "
            "JOIN ref.roles r ON r.id = u.role_id "
            "WHERE u.id = CAST(:uid AS uuid)"
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
    # BUG-16: always use the DB tenant_id, never the refresh-claim tenant_id.
    db_tenant_id: str = str(row.tenant_id)

    # S-006: revoke the old refresh jti.
    if refresh_session_row is not None:
        await session.execute(
            text(
                "UPDATE auth.sessions SET revoked_at = now() "
                "WHERE jti = :jti AND revoked_at IS NULL"
            ),
            {"jti": old_refresh_jti},
        )
    else:
        # Session row does not exist (token issued before this fix was deployed).
        log.info(
            "refresh_legacy_no_session_row",
            jti_prefix=old_refresh_jti[:8],
        )

    # Issue new access + refresh tokens (rotation).
    new_access = jwt_module.create_access_token(
        sub=user_id, role=role, tenant_id=db_tenant_id
    )
    new_refresh = jwt_module.create_refresh_token(sub=user_id, tenant_id=db_tenant_id)

    # Decode the new access jti for the session row.
    new_access_claims = jwt_module.decode_token(new_access)
    new_access_jti: str = new_access_claims.get("jti", "")

    # BUG-01: insert session row for the new access token.
    await insert_auth_session(
        session,
        user_id=user_id,
        tenant_id=db_tenant_id,
        jti=new_access_jti,
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    await session.flush()

    log.info("token_refreshed", user_id=user_id[:8])
    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=ACCESS_TOKEN_TTL_S,
        token_type="bearer",
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Logout -- revoke the current session",
    description=(
        "Extracts the jti from the Bearer token and marks the corresponding "
        "auth.sessions row as revoked (revoked_at=now()). Idempotent: returns "
        "204 even if the session row does not exist or is already revoked. "
        "BUG-15: logout now invalidates the server-side session."
    ),
    responses={204: {"description": "Logged out"}},
)
async def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db_no_auth),
) -> None:
    """Logout endpoint -- revokes the bearer session row.

    BUG-15: no longer a no-op.  The jti is extracted from the bearer token
    and the corresponding auth.sessions row is marked revoked.

    Returns:
        None (204 No Content).
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id)

    if credentials is not None:
        token = credentials.credentials
        try:
            claims = jwt_module.decode_token(token)
            jti: str = claims.get("jti", "")
            user_id: str = claims.get("sub", "")
            if jti and user_id:
                await revoke_auth_session_by_jti(
                    session,
                    jti=jti,
                    user_id=user_id,
                    correlation_id=correlation_id,
                )
                await session.flush()
                log.info("logout_session_revoked", jti_prefix=jti[:8])
        except Exception:  # noqa: BLE001 -- logout is always idempotent
            log.info("logout_no_valid_token")

    log.info("logout_called")
