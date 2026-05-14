"""Concrete FactorCatalogRepository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.infrastructure.db.models.factor import FactorCatalog


class FactorCatalogRepository:
    """Read-mostly repository for ref.factor_catalog.

    INSERT is allowed by data_steward before publishing.  After
    ``is_published=True`` the DB trigger blocks mutation (MG-02).
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an injected async session.

        Args:
            session: The active async SQLAlchemy session.
        """
        self._session = session

    async def get_by_factor_id(
        self,
        *,
        tenant_id: uuid.UUID,
        factor_id: str,
        gwp_set: str,
    ) -> FactorCatalog | None:
        """Fetch the current (valid_to IS NULL) factor row for a given factor_id + gwp_set.

        Args:
            tenant_id: Tenant UUID.
            factor_id: String factor identifier (e.g. 'STOICH_CACO3_IPCC_2006').
            gwp_set: GWP set ('AR6' or 'AR5').

        Returns:
            The matching ``FactorCatalog`` instance or None.
        """
        result = await self._session.execute(
            select(FactorCatalog).where(
                FactorCatalog.tenant_id == tenant_id,
                FactorCatalog.factor_id == factor_id,
                FactorCatalog.gwp_set == gwp_set,
                FactorCatalog.valid_to.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_tbc(self, tenant_id: uuid.UUID) -> Sequence[FactorCatalog]:
        """Return all factor rows still marked as TBC (pending numeric pinning).

        Used by ``seed_loader.py`` and MG-01 gate validation.

        Args:
            tenant_id: Tenant UUID.

        Returns:
            Sequence of ``FactorCatalog`` rows with ``is_tbc=True``.
        """
        result = await self._session.execute(
            select(FactorCatalog).where(
                FactorCatalog.tenant_id == tenant_id,
                FactorCatalog.is_tbc.is_(True),
            )
        )
        return result.scalars().all()

    async def get_by_uuid(
        self,
        *,
        tenant_id: uuid.UUID,
        factor_uuid: uuid.UUID,
    ) -> FactorCatalog | None:
        """Fetch a single factor row by its primary-key UUID, scoped to tenant.

        Used by the publish endpoint to enforce tenant isolation before the
        False→True transition on ``is_published``.

        Args:
            tenant_id: Tenant UUID (from JWT claim) — prevents cross-tenant access.
            factor_uuid: The UUID primary key of the factor row.

        Returns:
            The matching ``FactorCatalog`` instance or None.
        """
        result = await self._session.execute(
            select(FactorCatalog).where(
                FactorCatalog.tenant_id == tenant_id,
                FactorCatalog.id == factor_uuid,
            )
        )
        return result.scalar_one_or_none()

    async def insert(self, factor: FactorCatalog) -> FactorCatalog:
        """Insert a new factor catalog row (pre-publish only).

        Args:
            factor: ``FactorCatalog`` instance to persist.

        Returns:
            The persisted instance with DB-generated ``id``.
        """
        self._session.add(factor)
        await self._session.flush()
        return factor
