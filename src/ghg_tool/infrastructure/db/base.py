"""SQLAlchemy 2.x declarative base with explicit naming conventions.

All ORM models inherit from ``Base``.  The naming convention ensures
Alembic-generated constraint names are deterministic, which is required
for reproducible downgrade paths per AD-009.

Import direction: infrastructure.db imports nothing from application or api.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# ---------------------------------------------------------------------------
# Constraint naming convention — deterministic, Alembic-friendly
# ---------------------------------------------------------------------------
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Application-wide declarative base.

    All ORM models must inherit from this class.  The metadata carries the
    schema-aware naming conventions and is referenced by Alembic ``env.py``
    in wave 2 (when ``target_metadata = Base.metadata`` is uncommented).
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
