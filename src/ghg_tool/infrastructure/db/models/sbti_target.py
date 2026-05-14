"""ORM model for ref.sbti_targets -- SBTi-aligned reduction targets (ESRS E1-4).

Immutability semantics: the column ``is_active`` is the ONLY mutable field.
It may flip from True to False (deactivation) but never back to True. Any
other UPDATE, or a DELETE, is blocked by ``trg_sbti_target_immutability``
(defined in migration 0013_M12). This mirrors the append-only ledger
philosophy of the emissions and factor tables.

Only one active target per (tenant_id, scope_coverage) is permitted, enforced
by a partial UNIQUE index WHERE is_active = true (same migration).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class SbtiTarget(Base):
    """SBTi-aligned GHG reduction target (ref.sbti_targets).

    Corresponds 1-to-1 with the frozen dataclass
    ``ghg_tool.domain.entities.sbti_target.SbtiTarget``.

    Attributes:
        target_id: Primary key UUID.
        tenant_id: Owning tenant -- drives RLS filtering.
        name: Human-readable label for the target.
        scope_coverage: Scope mix (S1, S2_LB, S2_MB, S3, S1+S2_LB, S1+S2_MB,
            S1+S2_MB+S3). CHECK constraint mirrors ``_ALLOWED_SCOPES``.
        baseline_year: First year of the trajectory.
        baseline_tco2e: Emissions at baseline_year (Decimal, Numeric(18,3)).
        target_year: Final year of the trajectory (must be > baseline_year).
        target_tco2e: Emissions at target_year (must be <= baseline_tco2e).
        reduction_pct: Percentage reduction from baseline (stored for query
            convenience; computed by the service layer, never by the DB).
        alignment: Climate alignment label: 1.5C, WB2C, or 2C.
        methodology: Methodology label (SBTi_ACA, SDA, GEVA, etc.).
        sbti_approval_status: External SBTi validation status.
        sbti_validation_date: Date of SBTi validation (required when status
            is 'validated').
        created_by: UUID string of the creating user.
        created_at: Timestamp of row creation.
        is_active: Mutable flag; trigger allows only True -> False transition.
    """

    __tablename__ = "sbti_targets"
    __table_args__ = (
        CheckConstraint(
            "scope_coverage IN ("
            "'S1','S2_LB','S2_MB','S3',"
            "'S1+S2_LB','S1+S2_MB','S1+S2_MB+S3'"
            ")",
            name="chk_sbti_targets_scope_coverage",
        ),
        CheckConstraint(
            "alignment IN ('1.5C','WB2C','2C')",
            name="chk_sbti_targets_alignment",
        ),
        CheckConstraint(
            "methodology IN ("
            "'SBTi_ACA','SDA','GEVA','SBTi_NetZero',"
            "'supplier_engagement','custom'"
            ")",
            name="chk_sbti_targets_methodology",
        ),
        CheckConstraint(
            "sbti_approval_status IN ('none','committed','targets_set','validated')",
            name="chk_sbti_targets_sbti_approval_status",
        ),
        CheckConstraint(
            "target_year > baseline_year",
            name="chk_sbti_targets_year_order",
        ),
        CheckConstraint(
            "baseline_tco2e > 0",
            name="chk_sbti_targets_baseline_positive",
        ),
        CheckConstraint(
            "target_tco2e >= 0 AND target_tco2e <= baseline_tco2e",
            name="chk_sbti_targets_target_lte_baseline",
        ),
        Index(
            "ix_sbti_targets_tenant_year_active",
            "tenant_id",
            "target_year",
            "is_active",
        ),
        {"schema": "ref"},
    )

    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scope_coverage: Mapped[str] = mapped_column(String(40), nullable=False)
    baseline_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    baseline_tco2e: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    target_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_tco2e: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    reduction_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    alignment: Mapped[str] = mapped_column(String(10), nullable=False)
    methodology: Mapped[str] = mapped_column(String(40), nullable=False)
    sbti_approval_status: Mapped[str] = mapped_column(String(20), nullable=False)
    sbti_validation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
