"""Concrete EmissionsRepository — append-only implementation.

Implements the domain port ``domain.ports.emissions_repository.EmissionsRepositoryPort``.
UPDATE and DELETE methods are intentionally absent; only ``insert`` and
``get_by_id`` / ``get_active`` are exposed.  The DB trigger enforces this
at the persistence layer regardless.

Import direction: infrastructure → domain (allowed); never domain → infrastructure.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.infrastructure.db.models.emission import Emission


class EmissionsRepository:
    """Append-only repository for calc.emissions_consolidated.

    No UPDATE or DELETE methods.  Correction workflow uses the DB stored
    procedure ``calc.fn_emit_correction()`` called via ``execute()``.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an injected async session.

        Args:
            session: The active async SQLAlchemy session (with GUCs pre-set).
        """
        self._session = session

    async def insert(self, emission: Emission) -> Emission:
        """Append a new emission row (INSERT only).

        Args:
            emission: The ``Emission`` ORM instance to persist.

        Returns:
            The persisted instance with DB-generated ``id`` populated.
        """
        self._session.add(emission)
        await self._session.flush()
        return emission

    async def get_by_id(self, emission_id: uuid.UUID) -> Emission | None:
        """Fetch a single emission row by primary key.

        Args:
            emission_id: UUID primary key.

        Returns:
            The ``Emission`` instance, or None if not found.
        """
        result = await self._session.execute(
            select(Emission).where(Emission.id == emission_id)
        )
        return result.scalar_one_or_none()

    async def get_active(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: int | None = None,
        anno: int | None = None,
        codice_sito: str | None = None,
        regulatory_stream: str | None = None,
        gwp_set: str | None = None,
    ) -> Sequence[Emission]:
        """Fetch active (valid_to IS NULL) emission rows with optional filters.

        Args:
            tenant_id: Tenant UUID (RLS guard + explicit filter).
            scope: Optional scope filter (1, 2, or 3).
            anno: Optional reporting year filter.
            codice_sito: Optional site code filter.
            regulatory_stream: Optional stream filter ('CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV').
            gwp_set: Optional GWP set filter ('AR6' or 'AR5').

        Returns:
            Sequence of active ``Emission`` rows matching the filters.
        """
        stmt = select(Emission).where(
            Emission.tenant_id == tenant_id,
            Emission.valid_to.is_(None),
        )
        if scope is not None:
            stmt = stmt.where(Emission.scope == scope)
        if anno is not None:
            stmt = stmt.where(Emission.anno == anno)
        if codice_sito is not None:
            stmt = stmt.where(Emission.codice_sito == codice_sito)
        if regulatory_stream is not None:
            stmt = stmt.where(Emission.regulatory_stream == regulatory_stream)
        if gwp_set is not None:
            stmt = stmt.where(Emission.gwp_set == gwp_set)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def apply_correction(
        self,
        predecessor_id: uuid.UUID,
        new_id: uuid.UUID,
        reason_code: str,
    ) -> None:
        """Invoke ``calc.fn_emit_correction`` to close the predecessor row.

        This is the ONLY permitted quasi-update (closes valid_to / sets
        superseded_by / sets reason_code via SECURITY DEFINER procedure).

        Args:
            predecessor_id: UUID of the row to supersede.
            new_id: UUID of the newly inserted replacement row.
            reason_code: One of the approved correction reason codes.
        """
        from sqlalchemy import text  # local import to keep module-level clean
        await self._session.execute(
            text(
                "SELECT calc.fn_emit_correction("
                "   :predecessor_id::uuid, :new_id::uuid, :reason_code"
                ")"
            ),
            {
                "predecessor_id": str(predecessor_id),
                "new_id": str(new_id),
                "reason_code": reason_code,
            },
        )
