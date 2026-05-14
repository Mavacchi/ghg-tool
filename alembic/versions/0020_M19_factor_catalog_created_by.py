"""M19 -- factor_catalog.created_by column + self-approval DB CHECK.

Covers findings C-004 and C-006.

Changes (all additive / no DROP COLUMN):

1. ADD COLUMN ref.factor_catalog.created_by UUID NULL
   (nullable for back-fill safety; new rows set this from user.sub in the
   create endpoint via application code).
   Foreign key references ref.users.id.
   C-004.

2. ADD CONSTRAINT chk_no_self_approval on calc.factor_publish_approvals
   CHECK (approved_by IS NULL OR proposed_by <> approved_by)
   This is a DB-level defence-in-depth for the two-eyes ISAE 3000 control.
   The application layer already blocks self-approval (factor_catalog.py:921),
   but a future code path that bypasses the handler would still be caught here.
   C-006.

Revision: 0020_M19
Revises:  0019_M18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0020_M19"
down_revision: str = "0019_M18"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add created_by column and self-approval CHECK constraint."""

    # -------------------------------------------------------------------------
    # 1. ref.factor_catalog.created_by (C-004)
    # -------------------------------------------------------------------------
    op.add_column(
        "factor_catalog",
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("ref.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema="ref",
    )

    # -------------------------------------------------------------------------
    # 2. Self-approval CHECK on calc.factor_publish_approvals (C-006)
    # -------------------------------------------------------------------------
    op.create_check_constraint(
        "chk_no_self_approval",
        "factor_publish_approvals",
        "approved_by IS NULL OR proposed_by <> approved_by",
        schema="calc",
    )


def downgrade() -> None:
    """Reverse the created_by column and self-approval CHECK constraint."""

    op.drop_constraint(
        "chk_no_self_approval",
        "factor_publish_approvals",
        schema="calc",
        type_="check",
    )

    op.drop_column("factor_catalog", "created_by", schema="ref")
