"""Concrete DQFindingsRepository — append-only."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.infrastructure.db.models.dlq import Dlq
from ghg_tool.infrastructure.db.models.dq_finding import DqFinding


class DQFindingsRepository:
    """Repository for calc.dq_findings and calc.dlq (both append-only)."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an injected async session.

        Args:
            session: The active async SQLAlchemy session.
        """
        self._session = session

    async def insert_finding(self, finding: DqFinding) -> DqFinding:
        """Append a new DQ finding row.

        Args:
            finding: ``DqFinding`` instance to persist.

        Returns:
            Persisted instance with DB-generated ``id``.
        """
        self._session.add(finding)
        await self._session.flush()
        return finding

    async def insert_dlq(self, dlq_entry: Dlq) -> Dlq:
        """Append a failed row to the Dead Letter Queue.

        Args:
            dlq_entry: ``Dlq`` instance to persist.

        Returns:
            Persisted instance with DB-generated ``id``.
        """
        self._session.add(dlq_entry)
        await self._session.flush()
        return dlq_entry

    async def get_open_findings(
        self,
        tenant_id: uuid.UUID,
        *,
        severity: str | None = None,
    ) -> Sequence[DqFinding]:
        """Fetch open DQ findings (resolution_status='OPEN').

        Args:
            tenant_id: Tenant UUID.
            severity: Optional filter ('CRIT', 'WARN', or 'INFO').

        Returns:
            Sequence of open ``DqFinding`` rows.
        """
        stmt = select(DqFinding).where(
            DqFinding.tenant_id == tenant_id,
            DqFinding.resolution_status == "OPEN",
        )
        if severity is not None:
            stmt = stmt.where(DqFinding.severity == severity)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_pending_dlq(self, tenant_id: uuid.UUID) -> Sequence[Dlq]:
        """Fetch DLQ entries with replay_status='PENDING'.

        Args:
            tenant_id: Tenant UUID.

        Returns:
            Sequence of pending ``Dlq`` rows for replay.
        """
        result = await self._session.execute(
            select(Dlq).where(
                Dlq.tenant_id == tenant_id,
                Dlq.replay_status == "PENDING",
            )
        )
        return result.scalars().all()
