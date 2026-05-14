"""ORM model for ref.tenants — multi-tenant root table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class Tenant(Base):
    """Represents one tenant in ref.tenants.

    v1 ships a single seeded tenant ('CERAMIC_TILE_CO') but the schema is
    designed for multi-tenant isolation (M4 RLS policies key on
    ``tenant_id`` propagated via the ``app.tenant_id`` GUC).

    This model exists primarily so that the SQLAlchemy ``MetaData`` can
    resolve the ``ForeignKey('ref.tenants.id')`` declarations scattered
    across the other ORM models (audit_log, emission, factor,
    go_certificate, ingestion_batch, raw_scope1/2/3, role, site, user,
    dlq).  Without this registration, attempting to flush any of those
    rows raises ``NoReferencedTableError`` at table-sort time.
    """

    __tablename__ = "tenants"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
