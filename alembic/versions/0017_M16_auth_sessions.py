"""M16 -- auth.sessions table for session tracking v2.

Creates auth.sessions with:
  - id UUID PK
  - user_id UUID FK ref.users
  - tenant_id UUID FK ref.tenants
  - jti VARCHAR(80) NOT NULL UNIQUE
  - created_at TIMESTAMPTZ DEFAULT now()
  - last_seen_at TIMESTAMPTZ DEFAULT now()
  - ip_address INET NULLABLE
  - user_agent TEXT NULLABLE
  - revoked_at TIMESTAMPTZ NULLABLE
  - revoked_by UUID NULLABLE

Index on (user_id, revoked_at) for list-my-sessions query.

Revision: 0017_M16
Revises:  0016_M15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, UUID

revision: str = "0017_M16"
down_revision: str = "0016_M15"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create auth schema (if absent) and auth.sessions table."""
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref.tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jti", sa.String(80), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", UUID(as_uuid=True), nullable=True),
        schema="auth",
    )

    op.create_index(
        "ix_auth_sessions_user_revoked",
        "sessions",
        ["user_id", "revoked_at"],
        schema="auth",
    )


def downgrade() -> None:
    """Drop auth.sessions table."""
    op.drop_index("ix_auth_sessions_user_revoked", table_name="sessions", schema="auth")
    op.drop_table("sessions", schema="auth")
