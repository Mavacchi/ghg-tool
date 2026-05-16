"""Users router - administrative endpoints (admin only).

Exposes the minimum set of operations the admin tier needs from the UI
without having to drop to the ``scripts/create_user.py`` CLI:

  - ``GET /api/v1/users``  - list users in the caller's tenant.
  - ``POST /api/v1/users`` - create a new user with a bcrypt-hashed password.
  - ``PATCH /api/v1/users/{user_uuid}/active``   - activate / deactivate.
  - ``PATCH /api/v1/users/{user_uuid}/role``      - change role.
  - ``POST /api/v1/users/{user_uuid}/password-reset`` - admin password reset.

All write endpoints require ``users.write`` (admin only).
"""

from __future__ import annotations

import secrets
import string
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.api.schemas.user_schemas import (
    UserActivePatchRequest,
    UserErasureResponse,
    UserPasswordResetRequest,
    UserPasswordResetResponse,
    UserRolePatchRequest,
)
from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.security import siem
from ghg_tool.infrastructure.security.password import hash_password

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])

_VALID_ROLES = frozenset({"editor", "admin", "viewer"})

# Alphabet for server-side password generation: all printable ASCII except
# ambiguous characters (0, O, I, l) and shell-special characters.
_PWD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"


class UserListItem(BaseModel):
    """Public projection of a row in ``ref.users`` - no password hash."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    username: str
    email: str
    role_code: str
    is_active: bool


class UserCreateRequest(BaseModel):
    """Body for ``POST /api/v1/users`` - admin user creation.

    Username and email follow conservative validation to avoid odd payloads
    landing in the audit log. Password is bcrypt-hashed server-side; the
    plaintext is never persisted or logged.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.\-]+$")
    email: EmailStr
    role_code: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=8, max_length=200)


class UserCreateResponse(UserListItem):
    """Response for a successful user creation - same shape as list item."""


# ---------------------------------------------------------------------------
# Helper: fetch user row within the caller's tenant (returns None if absent).
# ---------------------------------------------------------------------------

async def _fetch_user_in_tenant(
    session: AsyncSession,
    user_uuid: uuid.UUID,
    tenant_id: str,
) -> dict | None:
    """Fetch a single user row joined with its role_code.

    Returns None if not found or if the user belongs to a different tenant.
    Never trusts a client-supplied tenant identifier; always uses the
    caller's JWT-derived tenant_id.

    Args:
        session: Async DB session.
        user_uuid: Target user UUID from the URL path.
        tenant_id: Caller's tenant UUID string from the JWT.

    Returns:
        Row dict with keys: id, username, email, role_code, role_id, is_active.
        None if the user does not exist or belongs to a different tenant.
    """
    result = await session.execute(
        text(
            "SELECT u.id, u.username, u.email, r.role_code, u.role_id, "
            "       u.is_active, u.password_hash "
            "FROM ref.users u JOIN ref.roles r ON r.id = u.role_id "
            "WHERE u.id = CAST(:uid AS uuid) "
            "  AND u.tenant_id = CAST(:tenant AS uuid)"
        ),
        {"uid": str(user_uuid), "tenant": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "id": row.id,
        "username": row.username,
        "email": row.email,
        "role_code": row.role_code,
        "role_id": row.role_id,
        "is_active": row.is_active,
        "password_hash": row.password_hash,
    }


async def _count_active_admins(
    session: AsyncSession,
    tenant_id: str,
) -> int:
    """Count active admin rows in the tenant.

    Used to enforce the 'last_admin' guard on deactivation and role demotion.

    Args:
        session: Async DB session.
        tenant_id: Caller's tenant UUID string from the JWT.

    Returns:
        Number of active admin users in the tenant.
    """
    result = await session.execute(
        text(
            "SELECT COUNT(*) FROM ref.users u "
            "JOIN ref.roles r ON r.id = u.role_id "
            "WHERE u.tenant_id = CAST(:tenant AS uuid) "
            "  AND r.role_code = 'admin' "
            "  AND u.is_active = TRUE"
        ),
        {"tenant": tenant_id},
    )
    row = result.fetchone()
    return int(row[0]) if row else 0


def _problem(
    status_code: int,
    title: str,
    detail: str,
    error_code: str,
    correlation_id: str | None,
) -> HTTPException:
    """Build an RFC 7807 problem+json HTTPException.

    Args:
        status_code: HTTP status code.
        title: Short title.
        detail: Human-readable detail message.
        error_code: Machine-readable error code.
        correlation_id: Request correlation UUID string.

    Returns:
        HTTPException with RFC 7807 body.
    """
    return HTTPException(
        status_code=status_code,
        detail={
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "error_code": error_code,
            "detail": detail,
            "correlation_id": correlation_id,
        },
    )


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[UserListItem],
    status_code=status.HTTP_200_OK,
    summary="List users in the caller's tenant (admin only)",
    description=(
        "Returns all users belonging to the caller's tenant. Password hashes "
        "are never returned. ``admin`` role required."
    ),
    responses={
        200: {"description": "Users list"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
    },
)
async def list_users(
    user: CurrentUser = Depends(require_permission("users", "read")),
    session: AsyncSession = Depends(get_db),
) -> list[UserListItem]:
    """Return all users in the caller's tenant.

    Uses a raw SELECT joined to ``ref.roles`` so we can return the role
    code rather than its UUID; the UUID is internal-only.
    """
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("list_users")

    result = await session.execute(
        text(
            "SELECT u.id, u.username, u.email, r.role_code, u.is_active "
            "FROM ref.users u JOIN ref.roles r ON r.id = u.role_id "
            "WHERE u.tenant_id = CAST(:tenant AS uuid) "
            "ORDER BY u.created_at DESC"
        ),
        {"tenant": user.tenant_id},
    )
    rows = result.fetchall()
    return [
        UserListItem(
            id=row.id,
            username=row.username,
            email=row.email,
            role_code=row.role_code,
            is_active=row.is_active,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# POST /
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=UserCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user (admin only)",
    description=(
        "Inserts a new row in ``ref.users`` with a bcrypt-hashed password. "
        "The plaintext password is never logged or persisted. Returns 409 "
        "on UNIQUE (tenant_id, username) or (tenant_id, email) violation. "
        "``admin`` role required."
    ),
    responses={
        201: {"description": "User created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        409: {"description": "Username or email already exists in the tenant"},
        422: {"description": "Validation error (bad role, invalid email, ...)"},
    },
)
async def create_user(
    request: Request,
    body: UserCreateRequest,
    user: CurrentUser = Depends(require_permission("users", "write")),
    session: AsyncSession = Depends(get_db),
) -> UserCreateResponse:
    """Create a new user in the caller's tenant.

    The role_code must be one of the seeded values (editor,
    admin, viewer). Cross-tenant creation is impossible: the
    new row's tenant_id is taken from the caller's JWT, never from
    the request body.
    """
    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        new_username=body.username[:8],
    )

    if body.role_code not in _VALID_ROLES:
        log.warning("create_user_invalid_role", role_code=body.role_code)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "type": "about:blank",
                "title": "Unprocessable Entity",
                "status": 422,
                "error_code": "invalid_role",
                "detail": (
                    f"role_code={body.role_code!r} is not valid. "
                    f"Allowed: {sorted(_VALID_ROLES)}"
                ),
                "correlation_id": correlation_id,
            },
        )

    role_row = await session.execute(
        text("SELECT id FROM ref.roles WHERE role_code = :rc"),
        {"rc": body.role_code},
    )
    role = role_row.fetchone()
    if role is None:
        # ref.roles is seeded at M0 migration time. Reaching this branch
        # means the seed didn't run - surface as 500 with a clear hint
        # but no DSN / stack-trace leak.
        log.error("create_user_role_not_seeded")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Reference data missing. Contact your administrator.",
                "correlation_id": correlation_id,
            },
        )

    pwd_hash = hash_password(body.password)
    new_id = uuid.uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO ref.users "
                "(id, tenant_id, username, email, password_hash, role_id) "
                "VALUES (:id, CAST(:tenant AS uuid), :u, :e, :h, :rid)"
            ),
            {
                "id": new_id,
                "tenant": user.tenant_id,
                "u": body.username,
                "e": body.email,
                "h": pwd_hash,
                "rid": role.id,
            },
        )
    except Exception as exc:  # noqa: BLE001 - we translate DB errors uniformly
        # A UNIQUE violation on (tenant_id, username) or (tenant_id, email)
        # is the only realistic path. Other failures are surfaced as 500
        # by the global error handler.
        if "duplicate key" in str(exc).lower() or "unique" in str(exc).lower():
            log.warning("create_user_duplicate", error_class=type(exc).__name__)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "about:blank",
                    "title": "Conflict",
                    "status": 409,
                    "error_code": "duplicate_user",
                    "detail": (
                        "A user with that username or email already exists in this tenant."
                    ),
                    "correlation_id": correlation_id,
                },
            ) from exc
        raise

    # Audit row in the same transaction.
    session.add(
        AuditLog(
            tenant_id=uuid.UUID(user.tenant_id),
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=user.role,
            action="user_created",
            resource="users",
            resource_id=new_id,
            request_method="POST",
            request_path="/api/v1/users",
            status_code=201,
            ip_address=client_ip,
            user_agent=user_agent,
            after_state={
                # C-012: PII (username/email) removed from audit_log.after_state.
                # Forensic lookup uses the user_id UUID and joins ref.users for
                # human-readable details.  Audit_log retention is 10 years per
                # GDPR Art. 6(1)(c) + Art. 32; storing PII here would expand the
                # Art. 4(1) scope of audit_log beyond what is disclosed in the
                # Art. 30 register.
                "user_id": str(new_id),
                "tenant_id": user.tenant_id,
                "role_id": str(role.id),
                "is_active": True,
            },
        )
    )

    await session.flush()

    log.info("user_created", role_code=body.role_code)

    return UserCreateResponse(
        id=new_id,
        username=body.username,
        email=body.email,
        role_code=body.role_code,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# PATCH /{user_uuid}/active
# ---------------------------------------------------------------------------

@router.patch(
    "/{user_uuid}/active",
    response_model=UserListItem,
    status_code=status.HTTP_200_OK,
    summary="Activate or deactivate a user (admin only)",
    description=(
        "Updates the ``is_active`` flag for the target user within the "
        "caller's tenant. Cannot deactivate the caller's own account "
        "(422 ``self_deactivation_forbidden``) or the last active "
        "admin in the tenant (422 ``last_admin``). Writes an "
        "audit_log row and emits a SIEM event in the same transaction."
    ),
    responses={
        200: {"description": "User activation state updated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        404: {"description": "User not found or belongs to a different tenant"},
        422: {"description": "self_deactivation_forbidden or last_admin"},
    },
)
async def patch_user_active(
    user_uuid: uuid.UUID,
    request: Request,
    body: UserActivePatchRequest,
    caller: CurrentUser = Depends(require_permission("users", "write")),
    session: AsyncSession = Depends(get_db),
) -> UserListItem:
    """Activate or deactivate a user account.

    Guards:
    - Tenant isolation via WHERE clause on tenant_id from JWT.
    - Self-deactivation guard prevents the caller locking themselves out.
    - Last-admin guard prevents leaving the tenant without any active manager.

    Args:
        user_uuid: Target user UUID from the URL path.
        request: HTTP request (for audit metadata).
        body: ``UserActivePatchRequest`` with the desired ``is_active`` flag.
        caller: Authenticated admin from JWT.
        session: Async DB session.

    Returns:
        Updated ``UserListItem``.

    Raises:
        HTTPException: 404 if not found or wrong tenant.
        HTTPException: 422 for self-deactivation or last-admin scenarios.
    """
    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        tenant_id=caller.tenant_id,
        user=caller.sub[:8],
        ip_address=client_ip,
        user_agent=user_agent,
        target_user=str(user_uuid),
    )

    target = await _fetch_user_in_tenant(session, user_uuid, caller.tenant_id)
    if target is None:
        log.warning("patch_user_active_not_found")
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"User {user_uuid} not found.",
            "user_not_found",
            correlation_id,
        )

    # Guard: refuse to deactivate the caller's own account.
    if not body.is_active and str(user_uuid) == caller.sub:
        log.warning("patch_user_active_self_deactivation_blocked")
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unprocessable Entity",
            "You cannot deactivate your own account.",
            "self_deactivation_forbidden",
            correlation_id,
        )

    # Guard: refuse to deactivate the last active admin.
    if not body.is_active and target["role_code"] == "admin":
        active_managers = await _count_active_admins(session, caller.tenant_id)
        if active_managers <= 1:
            log.warning("patch_user_active_last_admin_blocked")
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Unprocessable Entity",
                "Cannot deactivate the last active admin in this tenant.",
                "last_admin",
                correlation_id,
            )

    before_state = {
        "is_active": target["is_active"],
        "role_code": target["role_code"],
    }
    after_state = {
        "is_active": body.is_active,
        "role_code": target["role_code"],
    }

    await session.execute(
        text(
            "UPDATE ref.users SET is_active = :active "
            "WHERE id = CAST(:uid AS uuid) "
            "  AND tenant_id = CAST(:tenant AS uuid)"
        ),
        {
            "active": body.is_active,
            "uid": str(user_uuid),
            "tenant": caller.tenant_id,
        },
    )

    action = "user_activated" if body.is_active else "user_deactivated"

    session.add(
        AuditLog(
            tenant_id=uuid.UUID(caller.tenant_id),
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=caller.role,
            action=action,
            resource="users",
            resource_id=user_uuid,
            request_method="PATCH",
            request_path=f"/api/v1/users/{user_uuid}/active",
            status_code=200,
            ip_address=client_ip,
            user_agent=user_agent,
            before_state=before_state,
            after_state=after_state,
        )
    )

    await session.flush()

    log.info(action, target_role=target["role_code"])

    siem.emit(
        event=action,
        correlation_id=correlation_id,
        tenant_id=caller.tenant_id,
        user_sub=caller.sub,
        severity="INFO",
        payload={"target_user": str(user_uuid), "is_active": body.is_active},
    )

    return UserListItem(
        id=user_uuid,
        username=target["username"],
        email=target["email"],
        role_code=target["role_code"],
        is_active=body.is_active,
    )


# ---------------------------------------------------------------------------
# PATCH /{user_uuid}/role
# ---------------------------------------------------------------------------

@router.patch(
    "/{user_uuid}/role",
    response_model=UserListItem,
    status_code=status.HTTP_200_OK,
    summary="Change a user's role (admin only)",
    description=(
        "Assigns a new role to the target user within the caller's tenant. "
        "Refuses to demote the last active admin (422 ``last_admin``). "
        "Writes an audit_log row with before/after role_code and emits a "
        "SIEM event at severity WARN (privilege change)."
    ),
    responses={
        200: {"description": "Role updated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        404: {"description": "User not found or belongs to a different tenant"},
        422: {"description": "last_admin - would remove the last admin"},
    },
)
async def patch_user_role(
    user_uuid: uuid.UUID,
    request: Request,
    body: UserRolePatchRequest,
    caller: CurrentUser = Depends(require_permission("users", "write")),
    session: AsyncSession = Depends(get_db),
) -> UserListItem:
    """Change the role assigned to a user.

    The new role_code is validated by the Pydantic Literal before the handler
    runs.  The handler then resolves the role_id FK from ref.roles, guards
    against removing the last admin, and performs the UPDATE.

    Args:
        user_uuid: Target user UUID from the URL path.
        request: HTTP request (for audit metadata).
        body: ``UserRolePatchRequest`` with the desired ``role_code``.
        caller: Authenticated admin from JWT.
        session: Async DB session.

    Returns:
        Updated ``UserListItem``.

    Raises:
        HTTPException: 404 if not found or wrong tenant.
        HTTPException: 422 if demoting the last active admin.
        HTTPException: 500 if ref.roles seed is missing.
    """
    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        tenant_id=caller.tenant_id,
        user=caller.sub[:8],
        ip_address=client_ip,
        user_agent=user_agent,
        target_user=str(user_uuid),
    )

    target = await _fetch_user_in_tenant(session, user_uuid, caller.tenant_id)
    if target is None:
        log.warning("patch_user_role_not_found")
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"User {user_uuid} not found.",
            "user_not_found",
            correlation_id,
        )

    # Guard: refuse to demote the last active admin.
    if (
        target["role_code"] == "admin"
        and body.role_code != "admin"
        and target["is_active"]
    ):
        active_managers = await _count_active_admins(session, caller.tenant_id)
        if active_managers <= 1:
            log.warning("patch_user_role_last_admin_blocked")
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Unprocessable Entity",
                "Cannot demote the last active admin in this tenant.",
                "last_admin",
                correlation_id,
            )

    # Resolve the new role_id FK.
    role_row = await session.execute(
        text("SELECT id FROM ref.roles WHERE role_code = :rc"),
        {"rc": body.role_code},
    )
    role = role_row.fetchone()
    if role is None:
        log.error("patch_user_role_seed_missing", role_code=body.role_code)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Reference data missing. Contact your administrator.",
                "correlation_id": correlation_id,
            },
        )

    before_state = {"role_code": target["role_code"]}
    after_state = {"role_code": body.role_code}

    await session.execute(
        text(
            "UPDATE ref.users SET role_id = CAST(:rid AS uuid) "
            "WHERE id = CAST(:uid AS uuid) "
            "  AND tenant_id = CAST(:tenant AS uuid)"
        ),
        {
            "rid": str(role.id),
            "uid": str(user_uuid),
            "tenant": caller.tenant_id,
        },
    )

    session.add(
        AuditLog(
            tenant_id=uuid.UUID(caller.tenant_id),
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=caller.role,
            action="user_role_changed",
            resource="users",
            resource_id=user_uuid,
            request_method="PATCH",
            request_path=f"/api/v1/users/{user_uuid}/role",
            status_code=200,
            ip_address=client_ip,
            user_agent=user_agent,
            before_state=before_state,
            after_state=after_state,
        )
    )

    await session.flush()

    log.info(
        "user_role_changed",
        before_role=target["role_code"],
        after_role=body.role_code,
    )

    siem.emit(
        event="user_role_changed",
        correlation_id=correlation_id,
        tenant_id=caller.tenant_id,
        user_sub=caller.sub,
        severity="WARN",
        payload={
            "target_user": str(user_uuid),
            "before_role": target["role_code"],
            "after_role": body.role_code,
        },
    )

    return UserListItem(
        id=user_uuid,
        username=target["username"],
        email=target["email"],
        role_code=body.role_code,
        is_active=target["is_active"],
    )


# ---------------------------------------------------------------------------
# POST /{user_uuid}/password-reset
# ---------------------------------------------------------------------------

def _generate_password(length: int = 16) -> str:
    """Generate a cryptographically secure random password.

    Uses ``secrets.choice`` which is backed by ``os.urandom`` (CSPRNG).
    The generated password contains only characters from ``_PWD_ALPHABET``
    so it is safely transmissible over JSON without escaping issues.

    Args:
        length: Desired password length (default 16).

    Returns:
        A random password string of the requested length.
    """
    return "".join(secrets.choice(_PWD_ALPHABET) for _ in range(length))


@router.post(
    "/{user_uuid}/password-reset",
    response_model=UserPasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin password reset (admin only)",
    description=(
        "Resets the target user's password within the caller's tenant. "
        "If ``new_password`` is null or omitted, a secure 16-character "
        "password is generated server-side. The plaintext is returned ONCE "
        "in the response body so the admin can communicate it; it is never "
        "logged or stored unencrypted. Writes an audit_log row carrying only "
        "``{reset_at: <iso8601>}`` in after_state - never the hash or plaintext."
    ),
    responses={
        200: {"description": "Password reset, new_password in response body"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role"},
        404: {"description": "User not found or belongs to a different tenant"},
    },
)
async def reset_user_password(
    user_uuid: uuid.UUID,
    request: Request,
    body: UserPasswordResetRequest | None = None,
    caller: CurrentUser = Depends(require_permission("users", "write")),
    session: AsyncSession = Depends(get_db),
) -> UserPasswordResetResponse:
    """Reset a user's password; return the new plaintext once.

    The plaintext password is NEVER written to any log, metric, or audit
    column.  The audit row records only the action and the timestamp.

    Args:
        user_uuid: Target user UUID from the URL path.
        request: HTTP request (for audit metadata).
        body: Optional ``UserPasswordResetRequest``; may be omitted entirely.
        caller: Authenticated admin from JWT.
        session: Async DB session.

    Returns:
        ``UserPasswordResetResponse`` containing the new plaintext password.

    Raises:
        HTTPException: 404 if not found or wrong tenant.
    """
    from datetime import UTC, datetime  # noqa: PLC0415 - lazy import is fine here

    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        tenant_id=caller.tenant_id,
        user=caller.sub[:8],
        ip_address=client_ip,
        user_agent=user_agent,
        target_user=str(user_uuid),
    )

    target = await _fetch_user_in_tenant(session, user_uuid, caller.tenant_id)
    if target is None:
        log.warning("reset_user_password_not_found")
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"User {user_uuid} not found.",
            "user_not_found",
            correlation_id,
        )

    # Determine the new password - generate if caller did not supply one.
    if body is None or body.new_password is None:
        new_plain = _generate_password(16)
    else:
        new_plain = body.new_password

    new_hash = hash_password(new_plain)

    await session.execute(
        text(
            "UPDATE ref.users SET password_hash = :h "
            "WHERE id = CAST(:uid AS uuid) "
            "  AND tenant_id = CAST(:tenant AS uuid)"
        ),
        {
            "h": new_hash,
            "uid": str(user_uuid),
            "tenant": caller.tenant_id,
        },
    )

    # S-014: revoke all active sessions for the target user so that any
    # concurrent sessions become invalid immediately after the password reset.
    revoke_result = await session.execute(
        text(
            "UPDATE auth.sessions SET revoked_at = now() "
            "WHERE user_id = CAST(:uid AS uuid) "
            "  AND revoked_at IS NULL"
        ),
        {"uid": str(user_uuid)},
    )
    revoked_sessions: int = revoke_result.rowcount  # type: ignore[assignment]

    reset_at = datetime.now(tz=UTC).isoformat()

    # after_state carries ONLY reset_at; never the hash or plaintext.
    session.add(
        AuditLog(
            tenant_id=uuid.UUID(caller.tenant_id),
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=caller.role,
            action="user_password_reset",
            resource="users",
            resource_id=user_uuid,
            request_method="POST",
            request_path=f"/api/v1/users/{user_uuid}/password-reset",
            status_code=200,
            ip_address=client_ip,
            user_agent=user_agent,
            after_state={"reset_at": reset_at},
        )
    )

    await session.flush()

    # Log the action - never include the password or its hash.
    # S-014: include the number of revoked sessions in the log for forensics.
    log.info(
        "user_password_reset",
        target_user=str(user_uuid),
        sessions_revoked=revoked_sessions,
    )

    siem.emit(
        event="user_password_reset",
        correlation_id=correlation_id,
        tenant_id=caller.tenant_id,
        user_sub=caller.sub,
        severity="WARN",
        payload={"target_user": str(user_uuid)},
    )

    return UserPasswordResetResponse(new_password=new_plain)


# ---------------------------------------------------------------------------
# DELETE /{user_uuid}  — GDPR Art. 17 right to erasure (pseudonymisation)
# ---------------------------------------------------------------------------


@router.delete(
    "/{user_uuid}",
    response_model=UserErasureResponse,
    status_code=status.HTTP_200_OK,
    summary="GDPR Art. 17 erasure: pseudonymise user (admin only)",
    description=(
        "Pseudonymises a user row so that no PII is accessible via the system "
        "while retaining the UUID FK in audit_log (CSRD Art. 23(2) requirement). "
        "The user row is NOT deleted: username, email, and password_hash are "
        "overwritten with deterministic sentinel values derived from the user UUID. "
        "The erased user cannot log in (password_hash='!erased', is_active=FALSE). "
        "All emission records linked to this user_id remain intact. "
        "An audit_log entry records the erasure event (event='user.erased'). "
        "``admin`` role required."
    ),
    responses={
        200: {"description": "User pseudonymised; PII fields replaced with sentinel"},
        401: {"description": "Not authenticated"},
        403: {"description": "Insufficient role — admin only"},
        404: {"description": "User not found or belongs to a different tenant"},
        409: {"description": "User has already been erased"},
    },
)
async def erase_user(
    user_uuid: uuid.UUID,
    request: Request,
    caller: CurrentUser = Depends(require_permission("users", "write")),
    session: AsyncSession = Depends(get_db),
) -> UserErasureResponse:
    """Pseudonymise a user (GDPR Art. 17 right to erasure with audit-trail retention).

    The user row is NOT deleted (audit retention) but its PII fields are replaced
    with a pseudonymised sentinel:
      - username    -> erased_<sha256(user_id)[:16]>
      - email       -> erased_<sha256(user_id)[:16]>@erased.invalid
      - password_hash -> '!erased'  (no login possible)
      - is_active   -> FALSE
      - erased_at   -> now()

    All emission records linked to this user_id remain intact (CSRD requirement).
    Audit log entries referencing this user_id FK are not modified; the pseudonym
    sentinel on the user row is sufficient for GDPR Art. 17 compliance while
    preserving audit-trail integrity.
    An audit log entry is written with the erasure event.

    Args:
        user_uuid: Target user UUID from the URL path.
        request: HTTP request (for audit metadata and client IP).
        caller: Authenticated admin from JWT (requires ``users.write`` permission).
        session: Async DB session (auto-committed by the get_db dependency).

    Returns:
        ``UserErasureResponse`` with the user_id, pseudonym, and erased_at timestamp.

    Raises:
        HTTPException: 404 if not found or belongs to a different tenant.
        HTTPException: 409 if the user is already erased (password_hash == '!erased').
    """
    import hashlib  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    correlation_id = get_correlation_id()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log = logger.bind(
        correlation_id=correlation_id,
        tenant_id=caller.tenant_id,
        user=caller.sub[:8],
        ip_address=client_ip,
        user_agent=user_agent,
        target_user=str(user_uuid)[:8],
    )

    # Verify the target user exists within the caller's tenant.
    target = await _fetch_user_in_tenant(session, user_uuid, caller.tenant_id)
    if target is None:
        log.warning("erase_user_not_found")
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"User {user_uuid} not found.",
            "user_not_found",
            correlation_id,
        )

    # Guard: refuse to erase an already-erased user (idempotency guard).
    if target.get("password_hash", "") == "!erased":
        log.warning("erase_user_already_erased")
        raise _problem(
            status.HTTP_409_CONFLICT,
            "Conflict",
            f"User {user_uuid} has already been erased.",
            "user_already_erased",
            correlation_id,
        )

    # Derive the pseudonym deterministically from the user UUID.
    # sha256(user_id_string)[:16] gives a stable, reproducible token that
    # a DPA can verify given the original UUID — without storing the UUID
    # in any human-readable field.
    sha = hashlib.sha256(str(user_uuid).encode()).hexdigest()[:16]
    pseudonym = f"erased_{sha}"
    pseudonym_email = f"{pseudonym}@erased.invalid"

    await session.execute(
        text(
            """
            UPDATE ref.users
            SET username      = :pseu,
                email         = :pseu_email,
                password_hash = '!erased',
                is_active     = FALSE,
                erased_at     = now()
            WHERE id = CAST(:user_id AS uuid)
              AND tenant_id = CAST(:tenant AS uuid)
            """
        ),
        {
            "pseu": pseudonym,
            "pseu_email": pseudonym_email,
            "user_id": str(user_uuid),
            "tenant": caller.tenant_id,
        },
    )

    # Also revoke all active sessions for the erased user so that any
    # concurrent sessions become invalid immediately (defence-in-depth;
    # the erased password_hash already prevents re-login).
    await session.execute(
        text(
            "UPDATE auth.sessions SET revoked_at = now() "
            "WHERE user_id = CAST(:uid AS uuid) "
            "  AND revoked_at IS NULL"
        ),
        {"uid": str(user_uuid)},
    )

    erased_at = datetime.now(tz=UTC)

    # Write audit log entry.  The ``after_state`` records only the pseudonym
    # and the reason code — never the original PII fields.
    session.add(
        AuditLog(
            tenant_id=uuid.UUID(caller.tenant_id),
            correlation_id=uuid.UUID(correlation_id) if correlation_id else uuid.uuid4(),
            user_role=caller.role,
            action="user.erased",
            resource="users",
            resource_id=user_uuid,
            request_method="DELETE",
            request_path=f"/api/v1/users/{user_uuid}",
            status_code=200,
            ip_address=client_ip,
            user_agent=user_agent,
            after_state={
                "pseudonym": pseudonym,
                "reason_code": "GDPR_ART17",
                "erased_at": erased_at.isoformat(),
                # Retain actor UUID for forensic DPA lookup without PII.
                "actor_id": caller.sub,
            },
        )
    )

    await session.flush()

    log.info(
        "user_erased",
        target_user=str(user_uuid)[:8],
        pseudonym=pseudonym,
    )

    siem.emit(
        event="user.erased",
        correlation_id=correlation_id,
        tenant_id=caller.tenant_id,
        user_sub=caller.sub,
        severity="WARN",
        payload={
            "target_user": str(user_uuid)[:8],
            "pseudonym": pseudonym,
            "reason_code": "GDPR_ART17",
        },
    )

    return UserErasureResponse(
        user_id=user_uuid,
        pseudonym=pseudonym,
        erased_at=erased_at,
    )
