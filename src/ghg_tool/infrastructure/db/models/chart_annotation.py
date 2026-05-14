"""ORM for ops.chart_annotations.

Manual narrative annotations overlaid on dashboard charts. Append-only
post-insert except for ``is_visible`` and ``acknowledged_*`` columns
(see M15 migration immutability trigger).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class ChartAnnotation(Base):
    """Manual narrative attached to a dashboard chart (ops.chart_annotations).

    The annotation captures operational context the auditor would
    otherwise have to chase down by email - "why did Scope 1 drop 18%
    on VIANO in 2025? Because the kiln was offline Q3."

    Append-only by DB trigger: only is_visible and acknowledged_*
    columns may change post-insert; everything else is frozen.
    """

    __tablename__ = "chart_annotations"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'CRITICAL')",
            name="chk_chart_annotations_severity",
        ),
        {"schema": "ops"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ref.tenants.id"),
        nullable=False,
    )
    chart_key: Mapped[str] = mapped_column(String(80), nullable=False)
    anchor_year: Mapped[int | None] = mapped_column(SmallInteger)
    anchor_label: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default="INFO"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(120))
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
