"""ORM model for calc.dq_findings — append-only DQ gate findings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class DqFinding(Base):
    """Data quality finding produced by DQ gate checks (calc.dq_findings).

    Append-only: mutation blocked by ``trg_dq_findings_deny_mutation``.
    Resolution creates a new row with ``parent_finding_id`` pointing to
    the original, and ``resolution_status='REMEDIATED'`` or ``'WAIVED'``.
    """

    __tablename__ = "dq_findings"
    __table_args__ = {"schema": "calc"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calc.dq_findings.id")
    )
    rule_id: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[int | None] = mapped_column(SmallInteger)
    codice_sito: Mapped[str | None] = mapped_column(String(40))
    anno: Mapped[int | None] = mapped_column()
    metric: Mapped[str | None] = mapped_column(String(100))
    value_observed: Mapped[float | None] = mapped_column(Numeric(20, 6))
    value_reference: Mapped[float | None] = mapped_column(Numeric(20, 6))
    ratio_yoy: Mapped[float | None] = mapped_column(Numeric(20, 6))
    z_score: Mapped[float | None] = mapped_column(Numeric(20, 6))
    trigger_desc: Mapped[str | None] = mapped_column(String)
    recommended_action: Mapped[str | None] = mapped_column(String)
    raw_row_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    blocks_pipeline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dq_report_version: Mapped[str] = mapped_column(String(40), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolution_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="OPEN"
    )
    waiver_reason_code: Mapped[str | None] = mapped_column(String(40))
    waiver_justification: Mapped[str | None] = mapped_column(String)
    waiver_approved_by: Mapped[str | None] = mapped_column(String(120))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
