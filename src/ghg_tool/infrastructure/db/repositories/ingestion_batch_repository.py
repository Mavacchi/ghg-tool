"""Concrete IngestionBatchRepository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ghg_tool.infrastructure.db.models.ingestion_batch import IngestionBatch


class IngestionBatchRepository:
    """Repository for raw.ingestion_batches (idempotency tracking)."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an injected async session.

        Args:
            session: The active async SQLAlchemy session.
        """
        self._session = session

    async def insert(self, batch: IngestionBatch) -> IngestionBatch:
        """Persist a new ingestion batch record.

        Args:
            batch: ``IngestionBatch`` instance to persist.

        Returns:
            Persisted instance with DB-generated ``batch_id``.
        """
        self._session.add(batch)
        await self._session.flush()
        return batch

    async def get_by_correlation_id(
        self, correlation_id: uuid.UUID
    ) -> IngestionBatch | None:
        """Fetch batch by correlation_id (idempotency check).

        Args:
            correlation_id: UUID matching ``ingestion_batches.correlation_id``.

        Returns:
            The ``IngestionBatch`` instance or None if not found.
        """
        result = await self._session.execute(
            select(IngestionBatch).where(
                IngestionBatch.correlation_id == correlation_id
            )
        )
        return result.scalar_one_or_none()
