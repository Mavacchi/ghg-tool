"""Database session dependency — wires JWT claims into the async session.

Combines the wave 1 ``get_db_session`` factory with the decoded JWT claims
from the auth dependency to inject ``app.tenant_id`` and ``app.role_code``
GUCs for PostgreSQL RLS (AD-008, SG-02/03).

Wave4 Task B: after GUC injection, calls ``get_or_provision_user`` so that
SSO-origin JWT users are lazily inserted into ``ref.users`` before any FK
constraint on ``audit_log.user_id`` can fire.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import (
    CurrentUser,
    get_current_user,
    get_or_provision_user,
)
from ghg_tool.infrastructure.db.session import AsyncSessionFactory, set_session_gucs


async def get_db(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: authenticated async DB session with RLS GUCs set.

    Yields an ``AsyncSession`` with ``app.tenant_id``, ``app.role_code``, and
    ``app.user_id`` injected via ``SET LOCAL`` so that all PostgreSQL RLS
    policies fire correctly for the authenticated user.

    Wave4 Task B: after GUC injection, lazily provisions a ``ref.users`` row
    for JWT-verified users who arrived from an external SSO and are not yet
    in the local users table.  This prevents FK violations on
    ``audit_log.user_id``.  The provisioning is idempotent and best-effort;
    a failure does not abort the request.

    Args:
        request: The incoming HTTP request (used to retrieve stashed JWT claims).
        user: The decoded current user from the auth dependency.

    Yields:
        An ``AsyncSession`` ready for use in route handlers.
    """
    async with AsyncSessionFactory() as session, session.begin():
        await set_session_gucs(
            session,
            tenant_id=user.tenant_id,
            role_code=user.role,
            user_id=user.sub,
        )
        # Task B: lazy user provisioning — idempotent, best-effort.
        jwt_claims: dict[str, Any] = getattr(request.state, "jwt_claims", {})
        if jwt_claims:
            await get_or_provision_user(
                session,
                jwt_payload=jwt_claims,
                tenant_id=user.tenant_id,
            )
        yield session


async def get_db_no_auth() -> AsyncGenerator[AsyncSession, None]:
    """Unauthenticated DB session for health-check endpoints only.

    Does NOT inject RLS GUCs — use only for ``/healthz`` and ``/readyz``
    which perform a minimal connectivity probe without touching tenant data.

    Yields:
        An ``AsyncSession`` without GUC injection.
    """
    async with AsyncSessionFactory() as session, session.begin():
        yield session


def get_repositories(session: AsyncSession) -> dict[str, Any]:
    """Instantiate all repository classes bound to the given session.

    Centralises repository construction so route handlers can destructure
    what they need from a single Depends call.

    Args:
        session: An active async SQLAlchemy session.

    Returns:
        A dict mapping repository names to instances.
    """
    from ghg_tool.infrastructure.db.repositories.dq_findings_repository import (
        DQFindingsRepository,
    )
    from ghg_tool.infrastructure.db.repositories.emissions_repository import (
        EmissionsRepository,
    )
    from ghg_tool.infrastructure.db.repositories.factor_catalog_repository import (
        FactorCatalogRepository,
    )

    return {
        "emissions": EmissionsRepository(session),
        "factors": FactorCatalogRepository(session),
        "dq_findings": DQFindingsRepository(session),
    }
