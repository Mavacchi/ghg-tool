"""ORM model for calc.dlq — Dead Letter Queue for failed ETL rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class Dlq(Base):
    """Dead Letter Queue entry (calc.dlq).

    Append-only: mutation blocked by ``trg_dlq_deny_mutation``.
    ``replay_status`` transitions from PENDING → REPLAYED or ABANDONED
    via a SECURITY DEFINER procedure (wave 2).
    ``raw_row_payload`` stores the full JSON of the failed row for replay.
    """

    __tablename__ = "dlq"
    __table_args__ = {"schema": "calc"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dq_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calc.dq_findings.id")
    )
    rule_id: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    codice_sito: Mapped[str | None] = mapped_column(String(40))
    anno: Mapped[int | None] = mapped_column()
    combustibile_or_voce: Mapped[str | None] = mapped_column(String(60))
    raw_row_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)  # type: ignore[type-arg]
    value_observed: Mapped[float | None] = mapped_column(Numeric(20, 6))
    threshold: Mapped[str | None] = mapped_column(String(120))
    z_score: Mapped[float | None] = mapped_column(Numeric(20, 6))
    ratio_yoy: Mapped[float | None] = mapped_column(Numeric(20, 6))
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    replay_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replayed_by: Mapped[str | None] = mapped_column(String(120))
