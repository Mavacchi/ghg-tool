"""M15 -- TOTP 2FA columns on ref.users.

Adds three columns to ref.users:
  - totp_secret VARCHAR(64) NULLABLE
  - totp_enabled BOOLEAN NOT NULL DEFAULT FALSE
  - totp_enrolled_at TIMESTAMPTZ NULLABLE

Revision: 0016_M15
Revises:  0015_M14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0016_M15"
down_revision: str = "0015_M14"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add TOTP columns to ref.users."""
    op.add_column(
        "users",
        sa.Column("totp_secret", sa.String(64), nullable=True),
        schema="ref",
    )
    op.add_column(
        "users",
        sa.Column(
            "totp_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        schema="ref",
    )
    op.add_column(
        "users",
        sa.Column(
            "totp_enrolled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="ref",
    )


def downgrade() -> None:
    """Remove TOTP columns from ref.users."""
    op.drop_column("users", "totp_enrolled_at", schema="ref")
    op.drop_column("users", "totp_enabled", schema="ref")
    op.drop_column("users", "totp_secret", schema="ref")
