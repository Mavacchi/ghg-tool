"""M9 -- Split published_at into created_at + published_at (MG-03 follow-up).

The original schema set ``published_at NOT NULL DEFAULT now()`` on
``ref.factor_catalog``, so every INSERT -- including draft rows -- received an
INSERT-time timestamp in that column.  Any export of draft factors therefore
showed a misleading "published" timestamp.

This migration:
  1. Adds ``created_at TIMESTAMPTZ NOT NULL DEFAULT now()`` (the true row-
     creation timestamp).
  2. Backfills ``created_at`` from the existing ``published_at`` so historical
     creation times are preserved.
  3. Strips the NOT NULL constraint and DEFAULT from ``published_at`` so the
     column now means "the moment of publication, if any".
  4. Strips NOT NULL from ``published_by`` for the same reason.
  5. NULLs both ``published_at`` and ``published_by`` for rows where
     ``is_published = false`` (draft rows).
  6. Adds a CHECK constraint that enforces: when published, both columns must
     be non-NULL; when draft, both may be NULL.

Revision: 0010_M9
Revises: 0009_M8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0010_M9"
down_revision: str = "0009_M8"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "factor_catalog"
_SCHEMA = "ref"
_CHECK_NAME = "chk_factor_publish_fields_consistent"
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Add created_at, relax published_at/published_by to nullable, enforce CHECK."""

    # 1. Add created_at -- nullable temporarily so we can backfill below.
    op.add_column(
        _TABLE,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema=_SCHEMA,
    )

    # 2. Backfill created_at from published_at (preserves historical INSERT times).
    op.execute(
        "UPDATE ref.factor_catalog SET created_at = published_at"
    )

    # 3. Now tighten created_at to NOT NULL (backfill guarantees no NULLs).
    op.alter_column(
        _TABLE,
        "created_at",
        nullable=False,
        server_default=sa.text("now()"),
        schema=_SCHEMA,
    )

    # 4. Drop NOT NULL + DEFAULT from published_at.
    op.alter_column(
        _TABLE,
        "published_at",
        nullable=True,
        server_default=None,
        schema=_SCHEMA,
    )

    # 5. Drop NOT NULL from published_by.
    op.alter_column(
        _TABLE,
        "published_by",
        nullable=True,
        schema=_SCHEMA,
    )

    # 6. NULL out published_at and published_by for all draft rows.
    op.execute(
        "UPDATE ref.factor_catalog "
        "SET published_at = NULL, published_by = NULL "
        "WHERE is_published = false"
    )

    # 7. Add consistency CHECK constraint.
    op.create_check_constraint(
        _CHECK_NAME,
        _TABLE,
        "(is_published = false) OR "
        "(is_published = true AND published_at IS NOT NULL AND published_by IS NOT NULL)",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Restore published_at/published_by to NOT NULL DEFAULT now(), drop created_at."""

    # 1. Drop the CHECK constraint added in upgrade().
    op.drop_constraint(_CHECK_NAME, _TABLE, schema=_SCHEMA)

    # 2. Backfill published_at NULLs with created_at so NOT NULL can be restored.
    op.execute(
        "UPDATE ref.factor_catalog "
        "SET published_at = created_at "
        "WHERE published_at IS NULL"
    )

    # 3. Backfill published_by NULLs with 'unknown' to satisfy the NOT NULL.
    op.execute(
        "UPDATE ref.factor_catalog "
        "SET published_by = 'unknown' "
        "WHERE published_by IS NULL"
    )

    # 4. Restore published_at NOT NULL DEFAULT now().
    op.alter_column(
        _TABLE,
        "published_at",
        nullable=False,
        server_default=sa.text("now()"),
        schema=_SCHEMA,
    )

    # 5. Restore published_by NOT NULL.
    op.alter_column(
        _TABLE,
        "published_by",
        nullable=False,
        schema=_SCHEMA,
    )

    # 6. Drop created_at.
    op.drop_column(_TABLE, "created_at", schema=_SCHEMA)
