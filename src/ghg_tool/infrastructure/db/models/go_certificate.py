"""ORM model for ref.go_certificate_evidence — GO QC checklist per MG-14."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ghg_tool.infrastructure.db.base import Base


class GoCertificate(Base):
    """GO certificate evidence record per methodology_validation.md §2.4.

    All 8 QC booleans must be TRUE for MB = 0 tCO2e/MWh to apply (MG-03).
    The ``ref.v_go_certificate_qc_pass`` DB view ANDs them for quick lookup.
    """

    __tablename__ = "go_certificate_evidence"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    go_id: Mapped[str] = mapped_column(String(80), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.sites.id"), nullable=False
    )
    anno: Mapped[int] = mapped_column(nullable=False)
    volume_mwh: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    vintage_year: Mapped[int] = mapped_column(nullable=False)
    cancellation_date: Mapped[date] = mapped_column(Date, nullable=False)
    beneficiary_legal_entity: Mapped[str] = mapped_column(String(200), nullable=False)
    country_of_issuance: Mapped[str] = mapped_column(String(40), nullable=False)
    technology: Mapped[str] = mapped_column(String(40), nullable=False)
    qc1_conveyed_claim_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qc2_unique_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qc3_redeemed_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qc4_vintage_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qc5_geographic_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qc6_scope_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qc7_exclusivity_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qc8_residual_mix_disclosed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pdf_evidence_uri: Mapped[str] = mapped_column(String, nullable=False)
    validated_by: Mapped[str] = mapped_column(String(120), nullable=False)
    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    site: Mapped[Site] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Site", back_populates="go_certificates", lazy="raise"
    )
