"""ORM model for calc.factor_publish_approvals (ISAE 3000 two-eyes principle)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class FactorPublishApproval(Base):
    """Two-eyes approval record for factor publication (ISAE 3000 §A99).

    A draft factor must be approved by a SECOND esg_manager before it can
    be published.  The same esg_manager who proposed the approval cannot
    also approve it (``proposed_by != approved_by`` enforced in the handler).

    The UNIQUE constraint ``(tenant_id, factor_id)`` ensures there is at
    most one active approval request per factor.  Completed rows (APPROVED
    or REJECTED) are protected by a trigger that prevents mutation after
    ``decision`` leaves PENDING.

    Attributes:
        id: Primary key UUID.
        tenant_id: Owning tenant.
        factor_id: FK to ``calc.factor_catalog.id``.
        proposed_by: UUID of the esg_manager who created the request.
        proposed_at: Timestamp of the request (DB default = now()).
        approved_by: UUID of the approving esg_manager (NULL until decided).
        approved_at: Timestamp of the decision (NULL until decided).
        decision: PENDING | APPROVED | REJECTED.
        decision_notes: Free-text notes for REJECTED decisions.
        correlation_id: Trace ID from the request that created this row.
    """

    __tablename__ = "factor_publish_approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "factor_id", name="uq_fpa_tenant_factor"),
        CheckConstraint(
            "decision IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="chk_fpa_decision",
        ),
        {"schema": "calc"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    factor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.factor_catalog.id"), nullable=False
    )
    proposed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.users.id"), nullable=False
    )
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    decision_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    reason_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
