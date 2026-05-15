"""M11 -- Create calc.factor_publish_approvals (ISAE 3000 two-eyes principle).

Implements the two-eyes approval workflow for factor publication (FR-12).
A draft factor requires a second esg_manager to approve before publication;
the proposer and approver cannot be the same user.

The table is append-only for completed rows (decision != 'PENDING').
A trigger blocks UPDATE/DELETE on rows where decision is APPROVED or
REJECTED, preserving the audit trail in line with CSRD ESRS 1 §85.

Revision: 0012_M11
Revises: 0011_M10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0012_M11"
down_revision: str = "0011_M10"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "calc"
_TABLE = "factor_publish_approvals"
_TRIGGER_FN = "trg_fn_fpa_deny_mutation"
_TRIGGER = "trg_fpa_deny_mutation"
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Create calc.factor_publish_approvals with constraints and trigger."""

    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("ref.tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "factor_id",
            sa.UUID(as_uuid=True),
            # 0001_M0 creates the table under ref.factor_catalog (no calc.* version
            # exists). The wave-2 author wrote 'calc.factor_catalog' here by mistake;
            # the FK then fails at runtime on real Postgres with UndefinedTable.
            sa.ForeignKey("ref.factor_catalog.id"),
            nullable=False,
        ),
        sa.Column(
            "proposed_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("ref.users.id"),
            nullable=False,
        ),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "approved_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("ref.users.id"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decision",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("decision_notes", sa.String(2000), nullable=True),
        sa.Column("correlation_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_code", sa.String(60), nullable=True),
        schema=_SCHEMA,
    )

    # CHECK: decision must be one of the three lifecycle states.
    op.create_check_constraint(
        "chk_fpa_decision",
        _TABLE,
        "decision IN ('PENDING', 'APPROVED', 'REJECTED')",
        schema=_SCHEMA,
    )

    # UNIQUE: one active approval request per factor per tenant.
    op.create_unique_constraint(
        "uq_fpa_tenant_factor",
        _TABLE,
        ["tenant_id", "factor_id"],
        schema=_SCHEMA,
    )

    # INDEX: fast lookup of pending approvals by tenant (dashboard query).
    op.create_index(
        "ix_fpa_tenant_decision",
        _TABLE,
        ["tenant_id", "decision"],
        schema=_SCHEMA,
    )

    # INDEX: factor_id lookup (publish endpoint checks for existing row).
    op.create_index(
        "ix_fpa_factor_id",
        _TABLE,
        ["factor_id"],
        schema=_SCHEMA,
    )

    # Trigger function: deny UPDATE/DELETE on completed (non-PENDING) rows.
    # PENDING rows may still be updated (to APPROVED/REJECTED). Once
    # decided, they are permanently frozen.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION calc.{_TRIGGER_FN}()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.decision != 'PENDING' THEN
                RAISE EXCEPTION
                    'factor_publish_approval row % is completed (%) and is immutable',
                    OLD.id, OLD.decision
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    # Attach the trigger to the table for both UPDATE and DELETE.
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON calc.{_TABLE}
        FOR EACH ROW
        EXECUTE FUNCTION calc.{_TRIGGER_FN}();
        """
    )


def downgrade() -> None:
    """Drop the trigger, function, and table."""

    op.execute(
        f"DROP TRIGGER IF EXISTS {_TRIGGER} ON calc.{_TABLE}"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS calc.{_TRIGGER_FN}()"
    )
    op.drop_index("ix_fpa_factor_id", table_name=_TABLE, schema=_SCHEMA)
    op.drop_index("ix_fpa_tenant_decision", table_name=_TABLE, schema=_SCHEMA)
    op.drop_table(_TABLE, schema=_SCHEMA)
