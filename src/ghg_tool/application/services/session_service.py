"""Session service -- INSERT helper for auth.sessions rows.

BUG-01 / S-007: Every token issuance (login, totp/challenge, refresh) must
INSERT a row into auth.sessions so that session revocation via Sessions v2
endpoints and SessionCheckMiddleware fail-closed logic can function.

Usage::

    from ghg_tool.application.services.session_service import insert_auth_session

    await insert_auth_session(
        session,
        user_id=user.sub,
        tenant_id=user.tenant_id,
        jti=jti,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_MAX_USER_AGENT_LEN = 500


async def insert_auth_session(
    session: "AsyncSession",
    *,
    user_id: str,
    tenant_id: str,
    jti: str,
    ip_address: str | None,
    user_agent: str | None,
    correlation_id: str = "",
) -> None:
    """Insert a new row into auth.sessions for a freshly-issued access token.

    Must be called BEFORE returning the token to the client so that
    SessionCheckMiddleware can validate the jti on the very first request.

    Args:
        session: Active async DB session.  The caller is responsible for
            committing/flushing.
        user_id: Subject UUID string from the JWT.
        tenant_id: Tenant UUID string from the JWT.
        jti: The jti claim from the newly-issued access token.
        ip_address: Client IP address (may be None in test contexts).
        user_agent: Raw User-Agent header (truncated to 500 chars).
        correlation_id: Request correlation ID for structured logging.

    Raises:
        Exception: Propagated from SQLAlchemy if the INSERT fails.  The
            caller should treat an INSERT failure as fatal and NOT return
            the token to the client (fail-closed).
    """
    log = logger.bind(correlation_id=correlation_id, jti_prefix=jti[:8])

    # Truncate user-agent to prevent oversize inserts.
    ua = (user_agent or "")[:_MAX_USER_AGENT_LEN] or None

    await session.execute(
        text(
            "INSERT INTO auth.sessions "
            "(id, user_id, tenant_id, jti, ip_address, user_agent) "
            "VALUES "
            "(gen_random_uuid(), CAST(:uid AS uuid), CAST(:tid AS uuid), "
            " :jti, CAST(:ip AS inet), :ua)"
        ),
        {
            "uid": user_id,
            "tid": tenant_id,
            "jti": jti,
            "ip": ip_address,
            "ua": ua,
        },
    )
    log.debug("auth_session_inserted", user_id=user_id[:8])


async def revoke_auth_session_by_jti(
    session: "AsyncSession",
    *,
    jti: str,
    user_id: str,
    correlation_id: str = "",
) -> int:
    """Set revoked_at=now() on the session row matching jti + user_id.

    BUG-15 / BUG-08 (logout): used by the logout endpoint and by the refresh
    rotation path.  Uses both jti AND user_id to prevent cross-user revocation.

    Args:
        session: Active async DB session.
        jti: The jti claim of the token to revoke.
        user_id: The subject UUID string; must match the session row.
        correlation_id: Request correlation ID for structured logging.

    Returns:
        Number of rows updated (0 if the session was not found or already
        revoked; 1 on success).
    """
    log = logger.bind(correlation_id=correlation_id, jti_prefix=jti[:8])
    result = await session.execute(
        text(
            "UPDATE auth.sessions "
            "SET revoked_at = now() "
            "WHERE jti = :jti "
            "  AND user_id = CAST(:uid AS uuid) "
            "  AND revoked_at IS NULL"
        ),
        {"jti": jti, "uid": user_id},
    )
    rowcount: int = result.rowcount  # type: ignore[assignment]
    log.debug("auth_session_revoked_by_jti", rowcount=rowcount)
    return rowcount
