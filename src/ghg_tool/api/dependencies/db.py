"""Database session dependency — wires JWT claims into the async session.

Combines the wave 1 ``get_db_session`` factory with the decoded JWT claims
from the auth dependency to inject ``app.tenant_id`` and ``app.role_code``
GUCs for PostgreSQL RLS (AD-008, SG-02/03).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.api.dependencies.auth import CurrentUser, get_current_user
from ghg_tool.infrastructure.db.session import AsyncSessionFactory, set_session_gucs


async def get_db(
    user: CurrentUser = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: authenticated async DB session with RLS GUCs set.

    Yields an ``AsyncSession`` with ``app.tenant_id``, ``app.role_code``, and
    ``app.user_id`` injected via ``SET LOCAL`` so that all PostgreSQL RLS
    policies fire correctly for the authenticated user.

    Args:
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
