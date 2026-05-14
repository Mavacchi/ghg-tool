"""ORM model for ref.gwp_sets — GWP100 values per IPCC assessment report."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base


class GwpSet(Base):
    """GWP100 reference values for AR6 (primary) and AR5 (EU ETS dual-track).

    Seeded in migration M0.  AR6 default: CH4=27.9, N2O=273.
    AR5 EU ETS: CH4=28, N2O=265 (per EU ETS 2023/2122 amendment).
    """

    __tablename__ = "gwp_sets"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    gwp_set: Mapped[str] = mapped_column(String(10), nullable=False)
    substance: Mapped[str] = mapped_column(String(40), nullable=False)
    gwp100: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    source_citation: Mapped[str] = mapped_column(String, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
