"""Users router - administrative endpoints (esg_manager only).

Exposes the minimum set of operations the admin tier needs from the UI
without having to drop to the ``scripts/create_user.py`` CLI:

  - ``GET /api/v1/users``  - list users in the caller's tenant.
  - ``POST /api/v1/users`` - create a new user with a bcrypt-hashed password.

Both endpoints require ``users.read`` / ``users.write`` permission, which
is granted only to ``esg_manager`` in ``PERMISSION_MATRIX``.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission
from ghg_tool.infrastructure.db.models.audit_log import AuditLog
from ghg_tool.infrastructure.security.password import hash_password

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])

_VALID_ROLES = frozenset({"data_steward", "esg_manager", "auditor"})


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


@router.get(
    "/",
    response_model=list[UserListItem],
    status_code=status.HTTP_200_OK,
    summary="List users in the caller's tenant (admin only)",
    description=(
        "Returns all users belonging to the caller's tenant. Password hashes "
        "are never returned. ``esg_manager`` role required."
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


@router.post(
    "/",
    response_model=UserCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user (admin only)",
    description=(
        "Inserts a new row in ``ref.users`` with a bcrypt-hashed password. "
        "The plaintext password is never logged or persisted. Returns 409 "
        "on UNIQUE (tenant_id, username) or (tenant_id, email) violation. "
        "``esg_manager`` role required."
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

    The role_code must be one of the seeded values (data_steward,
    esg_manager, auditor). Cross-tenant creation is impossible: the
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
                "username": body.username,
                "email": body.email,
                "role_code": body.role_code,
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
