"""ORM model for ref.factor_catalog — versioned emission factors."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class FactorCatalog(Base):
    """Versioned emission factor entry (ref.factor_catalog).

    Immutable post-publish: ``is_published=True`` triggers the
    ``trg_factor_immutable`` DB trigger (MG-02).

    ADR-007: ``biogenic_co2_kg_per_unit`` carries the biogenic CO2 companion
    value for cardboard / pallet factors (ECOINV_CARDBOARD_V3_10,
    ECOINV_PALLET_V3_10).  NULL + ``is_tbc=True`` until licence retrieval
    at Phase 5 closes OI-9.
    """

    __tablename__ = "factor_catalog"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    factor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    substance: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[int] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(20, 8))
    is_licence_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_tbc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    biogenic_co2_kg_per_unit: Mapped[float | None] = mapped_column(Numeric(20, 8))
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    gwp_set: Mapped[str] = mapped_column(String(10), nullable=False)
    vintage: Mapped[str | None] = mapped_column(String(40))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    applicability_note: Mapped[str | None] = mapped_column(String)
    pdf_source_uri: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_by: Mapped[str] = mapped_column(String(120), nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
