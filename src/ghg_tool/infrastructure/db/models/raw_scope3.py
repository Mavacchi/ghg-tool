"""ORM model for raw.scope3_ingestions — Scope 3 raw rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class RawScope3Ingestion(Base):
    """Raw Scope 3 row from scope3_categorie.csv (raw.scope3_ingestions).

    Append-only.  ``metadata_defaulted=True`` flags rows where FR-37
    ETL transform applied Fonte_Dato/Qualità_Dato/Stato_Dato defaults
    (10 Cat 3 WTT/T&D rows with blank metadata in the native CSV).
    Zero-quantity rows (Cat 4 Feldspati_Treno / Sabbie_Treno) are
    retained as explicit disclosures per FR-03.
    """

    __tablename__ = "scope3_ingestions"
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
    categoria_s3: Mapped[int] = mapped_column(nullable=False)
    sottocategoria: Mapped[str] = mapped_column(String(200), nullable=False)
    metodo: Mapped[str] = mapped_column(String(40), nullable=False)
    combustibile: Mapped[str | None] = mapped_column(String(40))
    quantita: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    unita: Mapped[str] = mapped_column(String(20), nullable=False)
    fonte_dato: Mapped[str] = mapped_column(String(120), nullable=False)
    qualita_dato: Mapped[str] = mapped_column(String(4), nullable=False)
    stato_dato: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String)
    metadata_defaulted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    defaulting_rule_id: Mapped[str | None] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ingested_by: Mapped[str] = mapped_column(String(120), nullable=False)
