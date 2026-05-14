"""ORM model for raw.scope2_ingestions — Scope 2 raw rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class RawScope2Ingestion(Base):
    """Raw Scope 2 row from scope2_elettricita.csv (raw.scope2_ingestions).

    Append-only.  ``voce_s2`` is constrained to
    {EE_Acquistata_GO, EE_Acquistata_Grid}.  ``strumento_mb`` carries
    the market-based instrument type (GO_GSE or Grid_Residual).
    """

    __tablename__ = "scope2_ingestions"
    __table_args__ = {"schema": "raw"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw.ingestion_batches.batch_id"), nullable=False
    )
    scope: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    anno: Mapped[int] = mapped_column(nullable=False)
    codice_sito: Mapped[str] = mapped_column(String(40), nullable=False)
    voce_s2: Mapped[str] = mapped_column(String(40), nullable=False)
    quantita: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    unita: Mapped[str] = mapped_column(String(20), nullable=False)
    strumento_mb: Mapped[str | None] = mapped_column(String(40))
    fonte_dato: Mapped[str] = mapped_column(String(120), nullable=False)
    qualita_dato: Mapped[str] = mapped_column(String(4), nullable=False)
    stato_dato: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String)
    provenance: Mapped[str | None] = mapped_column(String(60))
    provenance_rationale: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ingested_by: Mapped[str] = mapped_column(String(120), nullable=False)
