"""JWT authentication dependency — SG-01, NFR-05.

Extracts the ``Authorization: Bearer <token>`` header, decodes and validates
the JWT, and returns a ``CurrentUser`` Pydantic model for injection into route
handlers.  Raises 401 for all auth failures and 403 for RBAC failures
(handled in the RBAC middleware layer).

Wave4 Task B — JWT auto-provisioning (PR #43 integration-test fix):
    When a JWT-verified user's ``sub`` UUID is not present in ``ref.users``
    (typical for SSO-origin tokens), ``get_or_provision_user`` lazily inserts
    a row with role=viewer and claims-derived username/email.  This prevents
    FK violations on ``audit_log.user_id``.  The insert is idempotent:
    ON CONFLICT DO NOTHING prevents double-insert on concurrent requests.
    Auto-provisioned users start with the most-restrictive role; an admin
    must promote them explicitly.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# SEC-P1-004: jose -> PyJWT migration.
from jwt import ExpiredSignatureError
from jwt import PyJWTError as JWTError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.infrastructure.security import jwt as jwt_module
from ghg_tool.infrastructure.security import token_blacklist

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


async def get_or_provision_user(
    session: Any,
    jwt_payload: dict[str, Any],
    *,
    tenant_id: str,
) -> None:
    """Lazily provision a ``ref.users`` row for a JWT-verified but unknown user.

    Called on every authenticated request so that SSO-origin tokens whose
    ``sub`` UUID is not already in ``ref.users`` get a minimal row before
    any downstream FK constraint (e.g. ``audit_log.user_id``) fires.

    The insert is idempotent via ``ON CONFLICT (id) DO NOTHING``, so
    concurrent first-requests for the same user only produce one row.

    Default role is ``viewer`` (most restrictive).  An admin must promote
    the user explicitly to grant broader permissions.

    Username / email are extracted from standard OIDC claims:
      - ``preferred_username`` or ``sub[:8]`` prefixed with ``auto_``
      - ``email`` or ``auto_<sub[:8]>@unknown.local``

    Args:
        session: Async SQLAlchemy session (RLS GUCs already set by get_db).
        jwt_payload: Decoded JWT claims dict.
        tenant_id: UUID string of the tenant to associate the new user with.

    Returns:
        None.  All failures are logged but not raised so the request continues.
    """
    from sqlalchemy import text  # noqa: PLC0415

    user_id: str = jwt_payload.get("sub", "")
    if not user_id:
        return

    log = logger.bind(user_id=user_id[:8], source="jwt")

    try:
        # Fast path: check if the user already exists.
        exists_result = await session.execute(
            text("SELECT id FROM ref.users WHERE id = CAST(:id AS uuid) LIMIT 1"),
            {"id": user_id},
        )
        if exists_result.scalar_one_or_none() is not None:
            # Existing user — no action needed.
            return

        # Derive username and email from OIDC claims; never log raw values (PII).
        sub_prefix = user_id[:8]
        username: str = jwt_payload.get("preferred_username") or f"auto_{sub_prefix}"
        email: str = jwt_payload.get("email") or f"auto_{sub_prefix}@unknown.local"

        # Resolve the viewer role id.
        role_result = await session.execute(
            text("SELECT id FROM ref.roles WHERE role_code = 'viewer' LIMIT 1"),
        )
        viewer_role_id = role_result.scalar_one_or_none()
        if viewer_role_id is None:
            log.warning("user_auto_provision_skipped", reason="viewer_role_not_found")
            return

        # Insert with ON CONFLICT DO NOTHING for idempotency under concurrent requests.
        await session.execute(
            text(
                """
                INSERT INTO ref.users (
                    id, tenant_id, username, email,
                    password_hash, role_id, is_active
                ) VALUES (
                    CAST(:id AS uuid),
                    CAST(:tenant_id AS uuid),
                    :username,
                    :email,
                    :password_hash,
                    CAST(:role_id AS uuid),
                    TRUE
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": user_id,
                "tenant_id": tenant_id,
                "username": username,
                "email": email,
                # No real password — SSO users authenticate via token only.
                # A sentinel bcrypt-like string prevents accidental login via
                # password form (the string is not a valid bcrypt hash).
                "password_hash": "!sso_provisioned_no_password",
                "role_id": str(viewer_role_id),
            },
        )

        log.info(
            "user_auto_provisioned",
            user_id=user_id[:8],  # truncated — no full UUID in logs (NFR-08)
            source="jwt",
            default_role="viewer",
        )

    except Exception as exc:  # noqa: BLE001
        # Auto-provisioning is a best-effort operation.  Failures must not
        # abort the current request — the FK violation (if it occurs) will
        # surface as a 500 at the point of the actual FK-constrained insert,
        # which is a more actionable error than losing the whole request here.
        log.warning(
            "user_auto_provision_failed",
            error_type=type(exc).__name__,
        )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """FastAPI dependency: decode JWT and return the current user.

    Sets ``request.state.user_sub`` for rate-limit key extraction.
    Stashes decoded JWT claims in ``request.state.jwt_claims`` so that the
    ``get_db`` dependency can trigger auto-provisioning without re-decoding.

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

    # SEC-P1-007: server-side revocation check.  A token whose jti has been
    # blacklisted (via /auth/logout or refresh rotation) must be rejected even
    # though the signature and exp would otherwise validate.
    # REQUIRED-2: fail closed when the blacklist backend (Redis) is
    # unreachable — we map JWTUnavailableError to HTTP 503 rather than
    # admitting the request.
    jti_claim = claims.get("jti", "")
    if isinstance(jti_claim, str) and jti_claim:
        try:
            if token_blacklist.is_revoked(jti_claim):
                log.warning(
                    "JWT rejected: jti is on blacklist",
                    jti_prefix=jti_claim[:8],
                    probe_attempt=True,
                )
                raise _unauthorized("Token has been revoked")
        except token_blacklist.JWTUnavailableError as exc:
            log.error(
                "JWT blacklist backend unavailable; failing closed (503)",
                jti_prefix=jti_claim[:8],
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "type": "about:blank",
                    "title": "Service Unavailable",
                    "status": 503,
                    "detail": (
                        "Authorization subsystem is temporarily unavailable; "
                        "retry shortly."
                    ),
                    "correlation_id": get_correlation_id(),
                },
                headers={"Content-Type": "application/problem+json"},
            ) from exc

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

    # Store sub on request.state for rate-limit middleware.
    request.state.user_sub = user.sub
    # Stash full claims so get_db can call get_or_provision_user without
    # decoding the token a second time.
    request.state.jwt_claims = claims

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
