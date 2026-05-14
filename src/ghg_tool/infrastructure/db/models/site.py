"""ORM model for ref.sites — 7 Italian production sites."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ghg_tool.infrastructure.db.base import Base


class Site(Base):
    """Represents one of the 7 Italian production sites (ref.sites).

    IANO is the only site with EU ETS Annex I Activity 17 registration
    (OI-7 confirmed YES 2026-05-13).
    """

    __tablename__ = "sites"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    codice_sito: Mapped[str] = mapped_column(String(40), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    geography: Mapped[str] = mapped_column(String(40), nullable=False)
    eu_ets_installation_id: Mapped[str | None] = mapped_column(String(80))
    eu_ets_activity: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships (back-populated in wave 2 when GO evidence model added)
    go_certificates: Mapped[list[GoCertificate]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "GoCertificate", back_populates="site", lazy="raise"
    )
