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

    ``before_state`` / ``after_state`` JSONB columns are populated only where
    documented in the relevant router (e.g. emission corrections per FR-21,
    factor publications).  PII is excluded from these columns per NFR-08 / SG-07
    and GDPR Art. 5(1)(c) data minimisation:

    - ``after_state`` for ``action='user_created'`` stores the user UUID, tenant UUID,
      and role UUID only.  No ``username`` or ``email`` are stored.  Forensic lookup
      joins ``ref.users`` on ``user_id`` UUID for human-readable details (C-012).
    - ``ip_address`` (INET) and ``user_agent`` (TEXT) are stored per row and classified
      as GDPR Art. 4(1) personal data (CJEU Breyer C-582/14 for IP; WP29 Opinion 4/2007
      for UA-string fingerprinting).  Retention: 10 years per GDPR Art. 6(1)(c) +
      Art. 32 (security monitoring obligation).  IP and UA are disclosed in the Art. 30
      register under Art. 6(1)(f) legitimate interest (SIEM / security monitoring).
    - ``user_id`` is a UUID FK to ``ref.users``; it is pseudonymous, not directly
      identifiable.  Audit-trail forensic lookup uses the UUID to join ``ref.users``
      for the human-readable username where legally required (e.g. ISAE 3000 review).

    Retention: 10 years per CSRD Art. 19a assurance continuity requirement and
    GDPR Art. 6(1)(c) + Art. 32 security-monitoring obligation.
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
