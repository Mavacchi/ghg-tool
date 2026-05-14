"""M15 -- Chart annotations table.

ops.chart_annotations stores manual narrative annotations that
overlay charts on the dashboard. Use cases:

  - Mark a one-off operational event ("Stop linea VIANO Q3 2025")
    so subsequent viewers understand the YoY drop without re-asking.
  - Tag a methodology change ("Switch to ISPRA 2024 factor set,
    impact +1.2% on Scope 2 LB").
  - Pre-fill the audit narrative for ESRS E1 disclosures.

Append-only by design: an annotation is created, optionally
acknowledged or hidden (is_visible flag), but never edited in place.
The acknowledged_by/is_visible columns can transition true->false
or null->user_id; everything else is immutable post-insert.

Revision: 0018_M17
Revises: 0017_M16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# ---------------------------------------------------------------------------
revision: str = "0018_M17"
down_revision: str = "0017_M16"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Create ops.chart_annotations + the immutability trigger."""
    op.execute("CREATE SCHEMA IF NOT EXISTS ops;")

    op.create_table(
        "chart_annotations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ref.tenants.id"),
            nullable=False,
        ),
        # Where the annotation should attach.
        # chart_key identifies which chart on which page (e.g.
        # "home_total_trend", "drilldown_stacked", "yoy_scope3").
        sa.Column("chart_key", sa.String(80), nullable=False),
        # Optional anchor: a year, a site code, or a free-form data point.
        # Either anchor_year or anchor_label may be NULL.
        sa.Column("anchor_year", sa.SmallInteger, nullable=True),
        sa.Column("anchor_label", sa.String(80), nullable=True),
        # The narrative.
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.String(2000), nullable=False),
        # Severity for colour coding: INFO / WARNING / CRITICAL.
        sa.Column(
            "severity",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'INFO'"),
        ),
        # Metadata.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column(
            "is_visible",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column("acknowledged_by", sa.String(120), nullable=True),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("extra", JSONB, nullable=True),
        sa.CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'CRITICAL')",
            name="chk_chart_annotations_severity",
        ),
        schema="ops",
    )

    op.create_index(
        "ix_chart_annotations_tenant_chart",
        "chart_annotations",
        ["tenant_id", "chart_key", "anchor_year"],
        schema="ops",
        postgresql_where=sa.text("is_visible = TRUE"),
    )

    # Immutability trigger: title, body, anchor_year, anchor_label,
    # severity, created_by, created_at, tenant_id, chart_key cannot
    # change after insert. Only is_visible, acknowledged_by,
    # acknowledged_at can transition.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.fn_chart_annotation_immutability()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.title IS DISTINCT FROM NEW.title
               OR OLD.body IS DISTINCT FROM NEW.body
               OR OLD.anchor_year IS DISTINCT FROM NEW.anchor_year
               OR OLD.anchor_label IS DISTINCT FROM NEW.anchor_label
               OR OLD.severity IS DISTINCT FROM NEW.severity
               OR OLD.created_by IS DISTINCT FROM NEW.created_by
               OR OLD.created_at IS DISTINCT FROM NEW.created_at
               OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
               OR OLD.chart_key IS DISTINCT FROM NEW.chart_key
            THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'P0001',
                    MESSAGE = 'chart_annotations rows are immutable except for is_visible / acknowledged_*';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_chart_annotation_immutability
        BEFORE UPDATE ON ops.chart_annotations
        FOR EACH ROW
        EXECUTE FUNCTION ops.fn_chart_annotation_immutability();

        -- DELETE is forbidden entirely.
        CREATE OR REPLACE FUNCTION ops.fn_chart_annotation_no_delete()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = 'P0001',
                MESSAGE = 'chart_annotations rows cannot be deleted; toggle is_visible instead';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_chart_annotation_no_delete
        BEFORE DELETE ON ops.chart_annotations
        FOR EACH ROW
        EXECUTE FUNCTION ops.fn_chart_annotation_no_delete();
        """
    )

    # RLS for tenant isolation.
    op.execute(
        """
        ALTER TABLE ops.chart_annotations ENABLE ROW LEVEL SECURITY;

        CREATE POLICY p_chart_annotations_tenant ON ops.chart_annotations
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    """Drop the table and its triggers."""
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_chart_annotation_no_delete
            ON ops.chart_annotations;
        DROP FUNCTION IF EXISTS ops.fn_chart_annotation_no_delete();
        DROP TRIGGER IF EXISTS trg_chart_annotation_immutability
            ON ops.chart_annotations;
        DROP FUNCTION IF EXISTS ops.fn_chart_annotation_immutability();
        """
    )
    op.drop_index(
        "ix_chart_annotations_tenant_chart",
        table_name="chart_annotations",
        schema="ops",
    )
    op.drop_table("chart_annotations", schema="ops")
