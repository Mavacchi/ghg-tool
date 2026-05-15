"""ORM model for ref.roles — RBAC roles."""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ghg_tool.infrastructure.db.base import Base

VALID_ROLE_CODES = frozenset({"editor", "admin", "viewer"})


class Role(Base):
    """RBAC role definition (ref.roles).

    Three roles are seeded in M0: editor, admin, viewer.
    """

    __tablename__ = "roles"
    __table_args__ = {"schema": "ref"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    role_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
