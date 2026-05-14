"""ORM model for calc.emissions_consolidated — the append-only emission store.

This is the single source of truth for all calculated GHG emissions.
UPDATE and DELETE are blocked by the ``trg_emissions_deny_mutation`` trigger
(M1 migration).  Corrections use ``calc.fn_emit_correction()`` only.

ADR-007: ``co2_biogenic_tonne`` and ``co2_fossil_tonne`` disclosed separately;
NEVER netted against ``tco2e``.  ESRS E1-7 governs biogenic disclosures.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class Emission(Base):
    """Append-only emission record (calc.emissions_consolidated).

    Every row carries full provenance: ``raw_row_id`` + ``factor_id`` +
    ``factor_version`` + ``gwp_set`` + ``methodology`` + ``correlation_id``
    per FR-22 / CG-04.  The natural key partial unique index ensures at most
    one active row per (tenant, scope, sub_scope, site, year, regulatory_stream,
    gwp_set) combination.
    """

    __tablename__ = "emissions_consolidated"
    __table_args__ = {"schema": "calc"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.tenants.id"), nullable=False
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    raw_row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    raw_scope: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scope: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sub_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    codice_sito: Mapped[str | None] = mapped_column(String(40))
    anno: Mapped[int] = mapped_column(nullable=False)
    tco2e: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    co2_tonne: Mapped[float | None] = mapped_column(Numeric(18, 6))
    ch4_tco2e: Mapped[float | None] = mapped_column(Numeric(18, 6))
    n2o_tco2e: Mapped[float | None] = mapped_column(Numeric(18, 6))
    # ADR-007: biogenic CO2 columns — separate from tco2e (ESRS E1-7)
    co2_biogenic_tonne: Mapped[float | None] = mapped_column(Numeric(18, 6))
    co2_fossil_tonne: Mapped[float | None] = mapped_column(Numeric(18, 6))
    factor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ref.factor_catalog.id"), nullable=False
    )
    factor_version: Mapped[str] = mapped_column(String(40), nullable=False)
    factor_source: Mapped[str] = mapped_column(String(40), nullable=False)
    gwp_set: Mapped[str] = mapped_column(String(10), nullable=False)
    methodology: Mapped[str] = mapped_column(String(40), nullable=False)
    regulatory_stream: Mapped[str] = mapped_column(
        String(40), nullable=False, default="CSRD_ESRS_E1"
    )
    calc_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calc.emissions_consolidated.id")
    )
    reason_code: Mapped[str | None] = mapped_column(String(40))
    disclosure_notes: Mapped[str | None] = mapped_column(Text)
