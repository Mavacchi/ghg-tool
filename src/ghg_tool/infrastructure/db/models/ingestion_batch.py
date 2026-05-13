"""ORM model for raw.ingestion_batches — ETL run correlation envelope."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class IngestionBatch(Base):
    """One ETL run correlating all raw rows inserted in a single pass.

    ``correlation_id`` == ``batch_id`` for ETL-triggered runs; may differ
    for API-sourced rows where the caller provides X-Correlation-Id.
    """

    __tablename__ = "ingestion_batches"
    __table_args__ = {"schema": "raw"}

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    run_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    run_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    etl_version: Mapped[str] = mapped_column(String(40), nullable=False)
    gwp_set: Mapped[str] = mapped_column(String(10), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(120), nullable=False)
    source_file_scope1_sha256: Mapped[str | None] = mapped_column(String(64))
    source_file_scope2_sha256: Mapped[str | None] = mapped_column(String(64))
    source_file_scope3_sha256: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(String)
