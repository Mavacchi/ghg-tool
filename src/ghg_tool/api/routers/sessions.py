"""Sessions v2 endpoints -- list, revoke, revoke-all.

GET    /api/v1/auth/sessions           -- list active sessions for the caller
DELETE /api/v1/auth/sessions/all       -- revoke all except current
DELETE /api/v1/auth/sessions/{session_id} -- revoke a specific session

NOTE: the /all path must be registered BEFORE /{session_id} so FastAPI
matches the literal "all" before the UUID parameter.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.api.dependencies.db import get_db
from ghg_tool.api.middleware.correlation_id import get_correlation_id
from ghg_tool.infrastructure.security import siem

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SessionItem(BaseModel):
    """Public projection of one auth.sessions row."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    ip_address: str | None
    user_agent: str | None
    is_current: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _problem(
    status_code: int,
    title: str,
    detail: str,
    error_code: str,
    correlation_id: str | None,
) -> HTTPException:
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
    response_model=list[SessionItem],
    status_code=status.HTTP_200_OK,
    summary="List my active sessions",
    description=(
        "Returns all non-revoked sessions for the authenticated user. "
        "The current session (matching the Bearer token's jti) is flagged "
        "with is_current=true. Scoped to the caller's tenant."
    ),
    responses={
        200: {"description": "Sessions list"},
        401: {"description": "Not authenticated"},
    },
)
async def list_sessions(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[SessionItem]:
    """Return active sessions for the caller."""
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    log.info("list_sessions")

    result = await session.execute(
        text(
            "SELECT id, created_at, last_seen_at, ip_address, user_agent, jti "
            "FROM auth.sessions "
            "WHERE user_id = CAST(:uid AS uuid) "
            "  AND tenant_id = CAST(:tenant AS uuid) "
            "  AND revoked_at IS NULL "
            "ORDER BY last_seen_at DESC"
        ),
        {"uid": user.sub, "tenant": user.tenant_id},
    )
    rows = result.fetchall()
    return [
        SessionItem(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            ip_address=str(row.ip_address) if row.ip_address else None,
            user_agent=row.user_agent,
            is_current=(row.jti == user.jti),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# DELETE /all
# ---------------------------------------------------------------------------


@router.delete(
    "/all",
    status_code=status.HTTP_200_OK,
    summary="Revoke all sessions except the current one",
    description=(
        "Sets revoked_at=now() on all non-current, non-already-revoked sessions "
        "for the caller. Useful when the user suspects account compromise. "
        "The current session (matched by jti) is preserved. Emits SIEM."
    ),
    responses={
        200: {"description": "All other sessions revoked"},
        401: {"description": "Not authenticated"},
    },
)
async def revoke_all_except_current(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Revoke every session except the current one."""
    correlation_id = get_correlation_id()
    log = logger.bind(correlation_id=correlation_id, user=user.sub[:8])
    now = datetime.now(tz=UTC)

    result = await session.execute(
        text(
            "UPDATE auth.sessions "
            "SET revoked_at = :now, revoked_by = CAST(:rby AS uuid) "
            "WHERE user_id = CAST(:uid AS uuid) "
            "  AND tenant_id = CAST(:tenant AS uuid) "
            "  AND jti != :current_jti "
            "  AND revoked_at IS NULL"
        ),
        {
            "now": now,
            "rby": user.sub,
            "uid": user.sub,
            "tenant": user.tenant_id,
            "current_jti": user.jti,
        },
    )
    revoked_count: int = result.rowcount  # type: ignore[assignment]
    await session.flush()

    log.info("sessions_revoke_all", revoked_count=revoked_count)
    siem.emit(
        event="sessions_revoke_all",
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user_sub=user.sub,
        severity="WARN",
        payload={"revoked_count": revoked_count},
    )
    return {"revoked": revoked_count}


# ---------------------------------------------------------------------------
# DELETE /{session_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_200_OK,
    summary="Revoke a specific session",
    description=(
        "Revokes the session identified by session_id. The session must belong "
        "to the caller's account and tenant (tenant isolation). Cannot revoke "
        "the current session (use logout instead): returns 422. "
        "Already-revoked sessions return 404."
    ),
    responses={
        200: {"description": "Session revoked"},
        401: {"description": "Not authenticated"},
        403: {"description": "Session belongs to another user"},
        404: {"description": "Session not found or already revoked"},
        422: {"description": "Cannot revoke current session via this endpoint"},
    },
)
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Revoke one session by id."""
    correlation_id = get_correlation_id()
    log = logger.bind(
        correlation_id=correlation_id,
        user=user.sub[:8],
        session_id=str(session_id),
    )

    # Fetch the session row to validate ownership.
    result = await session.execute(
        text(
            "SELECT id, user_id, tenant_id, jti, revoked_at "
            "FROM auth.sessions WHERE id = CAST(:sid AS uuid)"
        ),
        {"sid": str(session_id)},
    )
    row = result.fetchone()

    if row is None or row.revoked_at is not None:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Not Found",
            f"Session {session_id} not found or already revoked.",
            "session_not_found",
            correlation_id,
        )

    # Tenant + user ownership check.
    if str(row.user_id) != user.sub or str(row.tenant_id) != user.tenant_id:
        log.warning("session_revoke_forbidden", probe_attempt=True)
        raise _problem(
            status.HTTP_403_FORBIDDEN,
            "Forbidden",
            "This session does not belong to your account.",
            "session_ownership_mismatch",
            correlation_id,
        )

    # Cannot revoke the current session via DELETE -- use /logout.
    if row.jti == user.jti:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unprocessable Entity",
            "Cannot revoke the current session. Use POST /api/v1/auth/logout instead.",
            "cannot_revoke_current_session",
            correlation_id,
        )

    now = datetime.now(tz=UTC)
    await session.execute(
        text(
            "UPDATE auth.sessions SET revoked_at = :now, revoked_by = CAST(:rby AS uuid) "
            "WHERE id = CAST(:sid AS uuid)"
        ),
        {"now": now, "rby": user.sub, "sid": str(session_id)},
    )
    await session.flush()

    log.info("session_revoked")
    siem.emit(
        event="session_revoked",
        correlation_id=correlation_id,
        tenant_id=user.tenant_id,
        user_sub=user.sub,
        severity="INFO",
        payload={"session_id": str(session_id)},
    )
    return {"detail": f"Session {session_id} revoked."}
