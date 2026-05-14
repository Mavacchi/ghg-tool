"""M10 -- Create ops.calc_runs audit table.

Records one row per calc pipeline invocation. Gives operators an audit
trail of when emissions were calculated, how many rows were produced,
which GWP set and regulatory stream were used, and how long the run took.

The table lives in the ``ops`` schema alongside future operational tables
(scheduler state, retry queues, etc.).

Revision: 0011_M10
Revises: 0010_M9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0011_M10"
down_revision: str = "0010_M9"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "ops"
_TABLE = "calc_runs"
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Create ops schema (if absent) and the calc_runs table."""

    # Create ops schema -- harmless if it already exists.
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("ref.tenants.id"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("anno", sa.SmallInteger, nullable=False),
        sa.Column("emissions_written", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column(
            "gwp_set",
            sa.String(10),
            nullable=False,
        ),
        sa.Column(
            "regulatory_stream",
            sa.String(40),
            nullable=False,
            server_default="CSRD_ESRS_E1",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(120),
            nullable=False,
        ),
        schema=_SCHEMA,
    )

    # Index: fast lookup by tenant + anno (dashboard filter pattern).
    op.create_index(
        "ix_calc_runs_tenant_anno",
        _TABLE,
        ["tenant_id", "anno"],
        schema=_SCHEMA,
    )

    # Index: correlation_id lookup (trace a calc run from an emission row).
    op.create_index(
        "ix_calc_runs_correlation_id",
        _TABLE,
        ["correlation_id"],
        schema=_SCHEMA,
    )

    # CHECK: gwp_set must be one of the two allowed codes.
    op.create_check_constraint(
        "chk_calc_runs_gwp_set",
        _TABLE,
        "gwp_set IN ('AR6', 'AR5')",
        schema=_SCHEMA,
    )

    # CHECK: regulatory_stream vocabulary.
    op.create_check_constraint(
        "chk_calc_runs_regulatory_stream",
        _TABLE,
        "regulatory_stream IN ('CSRD_ESRS_E1', 'EU_ETS_PHASE_IV')",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the calc_runs table (ops schema is left in place)."""

    op.drop_index("ix_calc_runs_correlation_id", table_name=_TABLE, schema=_SCHEMA)
    op.drop_index("ix_calc_runs_tenant_anno", table_name=_TABLE, schema=_SCHEMA)
    op.drop_table(_TABLE, schema=_SCHEMA)
