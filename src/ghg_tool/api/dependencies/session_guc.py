"""Session GUC dependency — sets PostgreSQL RLS context variables (SG-02/03).

This module wires the decoded JWT claims into the ``SET LOCAL`` GUC calls
that activate PostgreSQL Row-Level Security policies.  It is consumed by the
``get_db`` session dependency in ``dependencies/db.py``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.infrastructure.db.session import set_session_gucs


async def apply_session_gucs(
    session: AsyncSession,
    *,
    tenant_id: str,
    role_code: str,
    user_id: str | None = None,
) -> None:
    """Apply RLS GUCs to the current transaction.

    Delegates to ``infrastructure.db.session.set_session_gucs`` which uses
    parameterised ``set_config()`` calls (no string interpolation — SG-05).

    Args:
        session: The active async SQLAlchemy session.
        tenant_id: Tenant UUID string from the JWT ``tenant_id`` claim.
        role_code: RBAC role code from the JWT ``role`` claim.
        user_id: User UUID string from the JWT ``sub`` claim (optional).
    """
    await set_session_gucs(
        session,
        tenant_id=tenant_id,
        role_code=role_code,
        user_id=user_id,
    )
