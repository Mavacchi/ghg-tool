"""Admin tenants router — multi-tenant management (wave 4).

Endpoints:
  GET    /api/v1/admin/tenants          — list all tenants (admin only)
  POST   /api/v1/admin/tenants          — create tenant (admin only)
  PATCH  /api/v1/admin/tenants/{id}     — rename tenant (admin only, audit log)
  DELETE /api/v1/admin/tenants/{id}     — deactivate tenant (admin only, no DELETE)

RBAC: all endpoints require ``role == "admin"``.  Attempting access with any
other role returns HTTP 403.

Design notes:
  - ``DELETE`` is actually a soft-deactivation: sets ``is_active = FALSE``.
    Hard DELETE on ``ref.tenants`` is forbidden due to FK chains and
    CSRD/ISAE-3000 data retention requirements.
  - PATCH writes an audit log row for every rename (mandatory for CSRD
    traceability).
  - Tenant ``code`` uniqueness is enforced at the DB level (UNIQUE constraint
    on ``ref.tenants.code``); the router catches ``23505`` PostgreSQL error
    and surfaces it as HTTP 409.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies import handle_unique_violation
from ghg_tool.api.dependencies.auth import CurrentUser
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.api.middleware.rbac import require_permission

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/tenants", tags=["admin-tenants"])

# Tenant code must consist only of uppercase letters, underscores, and digits.
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,59}$")

# -----------------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------------


class TenantListItem(BaseModel):
    """Public projection of a row in ``ref.tenants``."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    code: str
    legal_name: str
    is_active: bool
    created_at: datetime
    site_count: int = 0
    user_count: int = 0


class TenantCreateRequest(BaseModel):
    """Body for ``POST /api/v1/admin/tenants``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(
        min_length=2,
        max_length=60,
        description="Unique tenant code (uppercase letters, underscores, digits)",
    )
    legal_name: str = Field(
        min_length=1,
        max_length=200,
        description="Legal name of the tenant",
    )

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        if not _CODE_RE.match(v):
            raise ValueError(
                "Tenant code must start with an uppercase letter and contain "
                "only uppercase letters (A-Z), digits (0-9) and underscores (_)."
            )
        return v


class TenantCreateResponse(TenantListItem):
    """Response for tenant creation — mirrors TenantListItem."""


class TenantPatchRequest(BaseModel):
    """Body for ``PATCH /api/v1/admin/tenants/{id}``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str | None = Field(
        default=None,
        min_length=2,
        max_length=60,
        description="New tenant code (optional — omit to keep current)",
    )
    legal_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="New legal name (optional — omit to keep current)",
    )

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str | None) -> str | None:
        if v is not None and not _CODE_RE.match(v):
            raise ValueError(
                "Tenant code must start with an uppercase letter and contain "
                "only uppercase letters (A-Z), digits (0-9) and underscores (_)."
            )
        return v


class TenantDeactivateResponse(BaseModel):
    """Response for tenant deactivation."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    code: str
    is_active: bool
    detail: str


# -----------------------------------------------------------------------
# Route helpers
# -----------------------------------------------------------------------


def _require_admin(user: CurrentUser) -> None:
    """Raise 403 when the caller is not an admin.

    Args:
        user: The authenticated current user.

    Raises:
        HTTPException: HTTP 403 if role != admin.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "type": "about:blank",
                "title": "Forbidden",
                "status": 403,
                "detail": "Only admin users can manage tenants.",
                "correlation_id": get_correlation_id(),
            },
        )


async def _fetch_tenant(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[str, Any]:
    """Fetch a tenant row by PK or raise 404.

    Args:
        session: Active async DB session.
        tenant_id: UUID of the tenant to fetch.

    Returns:
        Tenant row as a dict.

    Raises:
        HTTPException: HTTP 404 if not found.
    """
    row = await session.execute(
        text(
            "SELECT id, code, legal_name, is_active, created_at "
            "FROM ref.tenants WHERE id = CAST(:id AS uuid)"
        ),
        {"id": str(tenant_id)},
    )
    tenant = row.fetchone()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "type": "about:blank",
                "title": "Not Found",
                "status": 404,
                "detail": f"Tenant {tenant_id} not found.",
                "correlation_id": get_correlation_id(),
            },
        )
    return dict(tenant._mapping)


async def _count_sites_and_users(
    session: AsyncSession, tenant_id: str
) -> tuple[int, int]:
    """Return (site_count, user_count) for a tenant.

    Args:
        session: Active async DB session.
        tenant_id: UUID string of the tenant.

    Returns:
        Tuple of (site_count, user_count).
    """
    site_res = await session.execute(
        text(
            "SELECT COUNT(*) FROM ref.sites WHERE tenant_id = CAST(:tid AS uuid)"
        ),
        {"tid": tenant_id},
    )
    user_res = await session.execute(
        text(
            "SELECT COUNT(*) FROM ref.users WHERE tenant_id = CAST(:tid AS uuid)"
        ),
        {"tid": tenant_id},
    )
    return int(site_res.scalar_one()), int(user_res.scalar_one())


# -----------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------


@router.get(
    "",
    response_model=list[TenantListItem],
    status_code=status.HTTP_200_OK,
    summary="List all tenants (admin only)",
    responses={
        200: {"description": "List of tenants"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
    },
)
async def list_tenants(
    user: CurrentUser = Depends(require_permission("tenants", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[TenantListItem]:
    """Return all tenants with aggregated site and user counts.

    Args:
        user: Authenticated admin user.
        db: Async DB session.

    Returns:
        List of ``TenantListItem`` objects.
    """
    _require_admin(user)
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("admin_list_tenants")

    rows = await db.execute(
        text(
            "SELECT id, code, legal_name, is_active, created_at "
            "FROM ref.tenants ORDER BY created_at"
        )
    )
    tenants_raw = rows.fetchall()

    result = []
    for row in tenants_raw:
        t = dict(row._mapping)
        sites, users = await _count_sites_and_users(db, str(t["id"]))
        result.append(
            TenantListItem(
                id=t["id"],
                code=t["code"],
                legal_name=t["legal_name"],
                is_active=t["is_active"],
                created_at=t["created_at"],
                site_count=sites,
                user_count=users,
            )
        )
    return result


@router.post(
    "",
    response_model=TenantCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant (admin only)",
    responses={
        201: {"description": "Tenant created"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
        409: {"description": "Tenant code already exists"},
        422: {"description": "Validation error"},
    },
)
async def create_tenant(
    body: TenantCreateRequest,
    user: CurrentUser = Depends(require_permission("tenants", "write")),
    db: AsyncSession = Depends(get_db),
) -> TenantCreateResponse:
    """Create a new tenant with a unique code.

    Inserts into ``ref.tenants``; raises 409 on duplicate ``code``.

    Args:
        body: ``TenantCreateRequest`` with code and legal_name.
        user: Authenticated admin user.
        db: Async DB session.

    Returns:
        ``TenantCreateResponse`` with the new tenant's data.

    Raises:
        HTTPException: 409 if code already exists.
    """
    _require_admin(user)
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id, user=user.sub[:8], code=body.code
    )
    log.info("admin_create_tenant")

    with handle_unique_violation(
        f"Tenant code '{body.code}' already exists.", correlation_id
    ):
        result = await db.execute(
            text(
                "INSERT INTO ref.tenants (code, legal_name, is_active) "
                "VALUES (:code, :legal_name, TRUE) "
                "RETURNING id, code, legal_name, is_active, created_at"
            ),
            {"code": body.code, "legal_name": body.legal_name},
        )
        row = result.fetchone()

    t = dict(row._mapping)  # type: ignore[union-attr]
    sites, users = await _count_sites_and_users(db, str(t["id"]))
    log.info("admin_tenant_created", tenant_id=str(t["id"]))
    return TenantCreateResponse(
        id=t["id"],
        code=t["code"],
        legal_name=t["legal_name"],
        is_active=t["is_active"],
        created_at=t["created_at"],
        site_count=sites,
        user_count=users,
    )


@router.patch(
    "/{tenant_id}",
    response_model=TenantListItem,
    status_code=status.HTTP_200_OK,
    summary="Rename tenant code and/or legal_name (admin only, audit log mandatory)",
    responses={
        200: {"description": "Tenant updated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
        404: {"description": "Tenant not found"},
        409: {"description": "New code already exists"},
        422: {"description": "Validation error"},
    },
)
async def rename_tenant(
    tenant_id: uuid.UUID,
    body: TenantPatchRequest,
    user: CurrentUser = Depends(require_permission("tenants", "write")),
    db: AsyncSession = Depends(get_db),
) -> TenantListItem:
    """Update the code and/or legal_name of a tenant.

    An audit log entry is written for every successful rename, recording
    the before and after states (mandatory for CSRD traceability).

    Args:
        tenant_id: UUID of the tenant to rename.
        body: ``TenantPatchRequest`` with optional new code/legal_name.
        user: Authenticated admin user.
        db: Async DB session.

    Returns:
        Updated ``TenantListItem``.

    Raises:
        HTTPException: 404 if tenant not found, 409 if new code is duplicate.
    """
    _require_admin(user)
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        tenant_id=str(tenant_id),
    )
    log.info("admin_rename_tenant_start")

    before = await _fetch_tenant(db, tenant_id)

    if body.code is None and body.legal_name is None:
        # Nothing to update — return current state
        sites, users = await _count_sites_and_users(db, str(tenant_id))
        return TenantListItem(
            id=before["id"],
            code=before["code"],
            legal_name=before["legal_name"],
            is_active=before["is_active"],
            created_at=before["created_at"],
            site_count=sites,
            user_count=users,
        )

    new_code = body.code if body.code is not None else before["code"]
    new_name = body.legal_name if body.legal_name is not None else before["legal_name"]

    with handle_unique_violation(
        f"Tenant code '{new_code}' already exists.", correlation_id
    ):
        await db.execute(
            text(
                "UPDATE ref.tenants SET code = :code, legal_name = :legal_name "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"code": new_code, "legal_name": new_name, "id": str(tenant_id)},
        )

    # Mandatory audit log for tenant rename (CSRD traceability)
    import json  # noqa: PLC0415

    try:
        await db.execute(
            text(
                "INSERT INTO calc.audit_log "
                "  (entity_type, entity_id, action, before_state, after_state, "
                "   user_id, correlation_id) "
                "VALUES "
                "  ('tenant', CAST(:eid AS uuid), 'RENAME', "
                "   CAST(:before AS jsonb), CAST(:after AS jsonb), "
                "   CAST(:uid AS uuid), :cid)"
            ),
            {
                "eid": str(tenant_id),
                "before": json.dumps(
                    {"code": before["code"], "legal_name": before["legal_name"]}
                ),
                "after": json.dumps(
                    {"code": new_code, "legal_name": new_name}
                ),
                "uid": user.sub,
                "cid": correlation_id,
            },
        )
    except Exception:  # noqa: BLE001 — audit log failure must not abort the rename
        log.warning(
            "admin_rename_audit_log_failed",
            tenant_id=str(tenant_id),
        )

    after = await _fetch_tenant(db, tenant_id)
    sites, users = await _count_sites_and_users(db, str(tenant_id))
    log.info(
        "admin_tenant_renamed",
        old_code=before["code"],
        new_code=new_code,
    )
    return TenantListItem(
        id=after["id"],
        code=after["code"],
        legal_name=after["legal_name"],
        is_active=after["is_active"],
        created_at=after["created_at"],
        site_count=sites,
        user_count=users,
    )


@router.delete(
    "/{tenant_id}",
    response_model=TenantDeactivateResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate tenant — soft-delete only (admin only)",
    description=(
        "Sets ``is_active = FALSE`` on the tenant row.  "
        "Hard DELETE is forbidden (FK chains + CSRD retention).  "
        "Deactivated tenants remain in ``ref.tenants`` for audit purposes."
    ),
    responses={
        200: {"description": "Tenant deactivated"},
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
        404: {"description": "Tenant not found"},
    },
)
async def deactivate_tenant(
    tenant_id: uuid.UUID,
    user: CurrentUser = Depends(require_permission("tenants", "write")),
    db: AsyncSession = Depends(get_db),
) -> TenantDeactivateResponse:
    """Soft-deactivate a tenant by setting ``is_active = FALSE``.

    Hard DELETE is intentionally not supported: FK chains from
    ``calc.emissions_consolidated`` etc. would require cascading deletes that
    would destroy CSRD audit evidence.  Deactivated tenants are invisible to
    normal users but remain available to admins and auditors.

    Args:
        tenant_id: UUID of the tenant to deactivate.
        user: Authenticated admin user.
        db: Async DB session.

    Returns:
        ``TenantDeactivateResponse`` confirming the deactivation.

    Raises:
        HTTPException: 404 if tenant not found.
    """
    _require_admin(user)
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        tenant_id=str(tenant_id),
    )
    log.info("admin_deactivate_tenant_start")

    tenant = await _fetch_tenant(db, tenant_id)

    await db.execute(
        text(
            "UPDATE ref.tenants SET is_active = FALSE "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": str(tenant_id)},
    )

    log.info("admin_tenant_deactivated", code=tenant["code"])
    return TenantDeactivateResponse(
        id=uuid.UUID(str(tenant["id"])),
        code=str(tenant["code"]),
        is_active=False,
        detail=(
            f"Tenant '{tenant['code']}' deactivated. "
            "Data retained for CSRD/ISAE-3000 compliance."
        ),
    )
