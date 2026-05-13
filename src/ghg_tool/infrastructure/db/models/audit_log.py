"""ORM model for calc.audit_log — append-only action audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class AuditLog(Base):
    """Immutable audit log for all sensitive API and ETL operations (calc.audit_log).

    Append-only: mutation blocked by ``trg_audit_log_deny_mutation``.
    ``before_state`` / ``after_state`` are populated for correction operations
    only (FR-21 requirement).  PII is excluded from logs per NFR-08 / SG-07.
    """

    __tablename__ = "audit_log"
    __table_args__ = {"schema": "calc"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.users.id")
    )
    user_role: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    request_method: Mapped[str | None] = mapped_column(String(10))
    request_path: Mapped[str | None] = mapped_column(String)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String)
    before_state: Mapped[dict | None] = mapped_column(JSONB)  # type: ignore[type-arg]
    after_state: Mapped[dict | None] = mapped_column(JSONB)  # type: ignore[type-arg]
    extra: Mapped[dict | None] = mapped_column(JSONB)  # type: ignore[type-arg]
