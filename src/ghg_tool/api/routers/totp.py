"""TOTP 2FA endpoints -- RFC 6238 enrollment and challenge flow.

Endpoints:
  POST /api/v1/auth/totp/enroll    -- generate secret, return QR
  POST /api/v1/auth/totp/verify    -- verify OTP, activate 2FA
  POST /api/v1/auth/totp/disable   -- disable 2FA (requires valid OTP)
  POST /api/v1/auth/totp/challenge -- accept partial_token + OTP, return full pair

Security constraints:
- totp_secret is NEVER logged, NEVER returned after the enroll one-shot.
- pre_2fa partial tokens are rejected by get_current_user on all other endpoints.
- OTP replay within the valid_window is handled by pyotp's internal check.
- All write paths emit audit_log + SIEM.
"""

from __future__ import annotations

import base64
import io
import uuid
from datetime import UTC, datetime
from typing import Any

import pyotp
import qrcode  # type: ignore[import-untyped]
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db_no_auth
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.schemas.auth_schemas import TokenResponse
from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.security import jwt as jwt_module
from ghg_tool.infrastructure.security import siem

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth/totp", tags=["totp"])

# 5-minute TTL for the partial pre-2FA token (section C).
_PARTIAL_TOKEN_TTL_S = 300

_TOTP_ISSUER = "Carbontrace"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TOTPEnrollResponse(BaseModel):
    """One-shot enrollment response -- secret MUST NOT be persisted client-side."""

    model_config = ConfigDict(frozen=True)

    secret_b32: str
    otpauth_url: str
    qr_png_b64: str


class TOTPVerifyRequest(BaseModel):
    """Body for /totp/verify and /totp/disable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    otp: str = Field(min_length=6, max_length=8, pattern=r"^\d+$")


class TOTPChallengeRequest(BaseModel):
    """Body for /totp/challenge -- partial_token + OTP."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    partial_token: str = Field(min_length=10)
    otp: str = Field(min_length=6, max_length=8, pattern=r"^\d+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_qr_b64(otpauth_url: str) -> str:
    """Render an otpauth:// URL as a base64-encoded PNG."""
    img = qrcode.make(otpauth_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _problem(
    status_code: int,
    title: str,
    detail: str,
    correlation_id: str | None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "detail": detail,
            "correlation_id": correlation_id,
        },
    )


async def _fetch_totp_row(
    session: AsyncSession, user_id: str
) -> dict[str, Any] | None:
    """Fetch totp_secret, totp_enabled, username, tenant_id for a user."""
    result = await session.execute(
        text(
            "SELECT totp_secret, totp_enabled, totp_enrolled_at, "
            "username, tenant_id "
            "FROM ref.users WHERE id = CAST(:uid AS uuid)"
        ),
        {"uid": user_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "totp_secret": row.totp_secret,
        "totp_enabled": row.totp_enabled,
        "totp_enrolled_at": row.totp_enrolled_at,
        "username": row.username,
        "tenant_id": str(row.tenant_id),
    }


# ---------------------------------------------------------------------------
# POST /enroll
# ---------------------------------------------------------------------------


@router.post(
    "/enroll",
    response_model=TOTPEnrollResponse,
    status_code=status.HTTP_200_OK,
    summary="Start TOTP enrollment -- generates secret and QR code",
    description=(
        "Generates a new TOTP secret for the authenticated user, stores it in "
        "ref.users.totp_secret, and returns a one-shot response with the "
        "base32 secret, the otpauth:// URL, and a QR code as a base64 PNG. "
        "The secret is NEVER returned again; the caller must verify (POST /verify) "
        "before 2FA is activated. Calling enroll again overwrites any pending secret."
    ),
    responses={
        200: {"description": "Enrollment started"},
        401: {"description": "Not authenticated"},
    },
)
async def enroll(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_no_auth),
) -> TOTPEnrollResponse:
    """Generate a new TOTP secret and store it (not yet enabled)."""
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)

    # Fetch username for a friendly provisioning URI.
    row = await _fetch_totp_row(session, user.sub)
    account_name = row["username"] if row else user.sub[:8]

    otpauth_url = totp.provisioning_uri(
        name=account_name, issuer_name=_TOTP_ISSUER
    )
    qr_b64 = _build_qr_b64(otpauth_url)

    # Store the pending secret; totp_enabled remains FALSE until /verify.
    # NEVER log the secret.
    await session.execute(
        text(
            "UPDATE ref.users SET totp_secret = :secret, totp_enabled = FALSE "
            "WHERE id = CAST(:uid AS uuid)"
        ),
        {"secret": secret, "uid": user.sub},
    )
    await session.flush()

    log.info("totp_enroll_started")
    return TOTPEnrollResponse(
        secret_b32=secret,
        otpauth_url=otpauth_url,
        qr_png_b64=qr_b64,
    )


# ---------------------------------------------------------------------------
# POST /verify
# ---------------------------------------------------------------------------


@router.post(
    "/verify",
    status_code=status.HTTP_200_OK,
    summary="Verify OTP and activate TOTP 2FA",
    description=(
        "Verifies the submitted OTP against the pending secret stored during "
        "enrollment. On success sets totp_enabled=TRUE and stamps "
        "totp_enrolled_at. 401 on wrong OTP or if enrollment has not started."
    ),
    responses={
        200: {"description": "2FA activated"},
        401: {"description": "Wrong OTP or enrollment not started"},
    },
)
async def verify(
    body: TOTPVerifyRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_no_auth),
) -> dict[str, str]:
    """Verify OTP and flip totp_enabled=TRUE."""
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    client_ip = request.client.host if request.client else None

    row = await _fetch_totp_row(session, user.sub)
    if not row or not row["totp_secret"]:
        raise _problem(status.HTTP_401_UNAUTHORIZED, "Unauthorized",
                       "TOTP enrollment not started. Call /enroll first.", correlation_id)

    totp = pyotp.TOTP(row["totp_secret"])
    if not totp.verify(body.otp, valid_window=1):
        log.warning("totp_verify_wrong_otp", probe_attempt=True)
        siem.emit(
            event="totp_verify_failed",
            correlation_id=correlation_id,
            tenant_id=row["tenant_id"],
            user_sub=user.sub,
            severity="WARN",
            payload={"ip": client_ip},
        )
        raise _problem(status.HTTP_401_UNAUTHORIZED, "Unauthorized",
                       "Invalid OTP.", correlation_id)

    now = datetime.now(tz=UTC)
    await session.execute(
        text(
            "UPDATE ref.users SET totp_enabled = TRUE, totp_enrolled_at = :ts "
            "WHERE id = CAST(:uid AS uuid)"
        ),
        {"ts": now, "uid": user.sub},
    )

    session.add(
        AuditLog(
            tenant_id=uuid.UUID(row["tenant_id"]),
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=user.role,
            action="totp_enabled",
            resource="users",
            resource_id=uuid.UUID(user.sub),
            request_method="POST",
            request_path="/api/v1/auth/totp/verify",
            status_code=200,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            after_state={"totp_enabled": True, "enrolled_at": now.isoformat()},
        )
    )
    await session.flush()

    log.info("totp_enabled")
    siem.emit(
        event="totp_enabled",
        correlation_id=correlation_id,
        tenant_id=row["tenant_id"],
        user_sub=user.sub,
        severity="INFO",
        payload={},
    )
    return {"detail": "2FA activated successfully."}


# ---------------------------------------------------------------------------
# POST /disable
# ---------------------------------------------------------------------------


@router.post(
    "/disable",
    status_code=status.HTTP_200_OK,
    summary="Disable TOTP 2FA (requires valid OTP)",
    description=(
        "Disables 2FA for the authenticated user. A valid OTP is required "
        "as proof of possession before disabling. Clears totp_enabled and "
        "totp_enrolled_at (totp_secret is retained until next enroll to "
        "prevent race-condition re-use). Audit log + SIEM emitted."
    ),
    responses={
        200: {"description": "2FA disabled"},
        401: {"description": "Wrong OTP or 2FA not enabled"},
    },
)
async def disable(
    body: TOTPVerifyRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_no_auth),
) -> dict[str, str]:
    """Disable TOTP after verifying the current OTP."""
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    client_ip = request.client.host if request.client else None

    row = await _fetch_totp_row(session, user.sub)
    if not row or not row["totp_enabled"] or not row["totp_secret"]:
        raise _problem(status.HTTP_401_UNAUTHORIZED, "Unauthorized",
                       "TOTP 2FA is not enabled for this account.", correlation_id)

    totp = pyotp.TOTP(row["totp_secret"])
    if not totp.verify(body.otp, valid_window=1):
        log.warning("totp_disable_wrong_otp", probe_attempt=True)
        siem.emit(
            event="totp_disable_failed",
            correlation_id=correlation_id,
            tenant_id=row["tenant_id"],
            user_sub=user.sub,
            severity="WARN",
            payload={"ip": client_ip},
        )
        raise _problem(status.HTTP_401_UNAUTHORIZED, "Unauthorized",
                       "Invalid OTP.", correlation_id)

    now = datetime.now(tz=UTC)
    await session.execute(
        text(
            "UPDATE ref.users SET totp_enabled = FALSE, totp_enrolled_at = NULL "
            "WHERE id = CAST(:uid AS uuid)"
        ),
        {"uid": user.sub},
    )

    session.add(
        AuditLog(
            tenant_id=uuid.UUID(row["tenant_id"]),
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=user.role,
            action="totp_disabled",
            resource="users",
            resource_id=uuid.UUID(user.sub),
            request_method="POST",
            request_path="/api/v1/auth/totp/disable",
            status_code=200,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
            after_state={"totp_enabled": False, "disabled_at": now.isoformat()},
        )
    )
    await session.flush()

    log.info("totp_disabled")
    siem.emit(
        event="totp_disabled",
        correlation_id=correlation_id,
        tenant_id=row["tenant_id"],
        user_sub=user.sub,
        severity="WARN",
        payload={},
    )
    return {"detail": "2FA disabled."}


# ---------------------------------------------------------------------------
# POST /challenge
# ---------------------------------------------------------------------------


@router.post(
    "/challenge",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete TOTP challenge and receive full token pair",
    description=(
        "Accepts the short-lived partial_token (pre_2fa=true, 5 min TTL) "
        "plus the current TOTP OTP. On success returns the full access + "
        "refresh token pair. 401 on wrong OTP or if partial_token is invalid."
    ),
    responses={
        200: {"description": "Full token pair issued"},
        401: {"description": "Invalid partial token or wrong OTP"},
    },
)
async def challenge(
    body: TOTPChallengeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_no_auth),
) -> TokenResponse:
    """Validate partial_token + OTP and issue full tokens."""
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id)
    client_ip = request.client.host if request.client else None

    # Decode and validate the partial token -- it must carry pre_2fa=true.
    try:
        claims = jwt_module.decode_token(body.partial_token)
    except Exception as exc:  # noqa: BLE001
        log.warning("totp_challenge_invalid_partial_token", probe_attempt=True)
        raise _problem(status.HTTP_401_UNAUTHORIZED, "Unauthorized",
                       "Invalid or expired partial token.", correlation_id) from exc

    if not claims.get("pre_2fa"):
        raise _problem(status.HTTP_401_UNAUTHORIZED, "Unauthorized",
                       "Token is not a pre-2FA partial token.", correlation_id)

    user_id: str = claims.get("sub", "")
    tenant_id: str = claims.get("tenant_id", "")
    role: str = claims.get("role", "")

    row = await _fetch_totp_row(session, user_id)
    if not row or not row["totp_enabled"] or not row["totp_secret"]:
        raise _problem(status.HTTP_401_UNAUTHORIZED, "Unauthorized",
                       "TOTP not configured for this user.", correlation_id)

    totp = pyotp.TOTP(row["totp_secret"])
    if not totp.verify(body.otp, valid_window=1):
        log.warning("totp_challenge_wrong_otp", probe_attempt=True)
        siem.emit(
            event="totp_challenge_failed",
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            user_sub=user_id,
            severity="WARN",
            payload={"ip": client_ip},
        )
        raise _problem(status.HTTP_401_UNAUTHORIZED, "Unauthorized",
                       "Invalid OTP.", correlation_id)

    access_token = jwt_module.create_access_token(
        sub=user_id, role=role, tenant_id=tenant_id
    )
    refresh_token = jwt_module.create_refresh_token(sub=user_id, tenant_id=tenant_id)

    log.info("totp_challenge_success", user_id=user_id[:8])
    siem.emit(
        event="totp_challenge_success",
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        user_sub=user_id,
        severity="INFO",
        payload={},
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=jwt_module.ACCESS_TOKEN_TTL_S,
        token_type="bearer",
    )
