"""M13 -- calc.report_snapshots: frozen point-in-time emission filings.

A snapshot captures the consolidated emissions at the moment a CSRD ESRS E1
report (or interim package) is signed.  Every subsequent calc run can be
reconciled against the snapshot to produce a CSRD Article 23 / ESRS 2 BP-2
restatement diff.

Append-only via the shared ``ops.deny_mutation`` trigger.  Tenant-scoped via
RLS using the same ``app.tenant_id`` GUC pattern as M4.

Revision: 0012_M13
Revises: 0011_M10
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0012_M13"
down_revision: str = "0011_M10"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Create calc.report_snapshots, indexes, append-only trigger, RLS."""
    op.execute(
        """
        CREATE TABLE calc.report_snapshots (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID         NOT NULL REFERENCES ref.tenants(id),
            snapshot_kind           VARCHAR(40)  NOT NULL,
            anno                    SMALLINT     NOT NULL CHECK (anno BETWEEN 2020 AND 2099),
            snapshot_correlation_id UUID         NOT NULL,
            taken_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),
            taken_by                VARCHAR(120) NOT NULL,
            pdf_sha256              VARCHAR(64),
            frozen_emissions        JSONB        NOT NULL,
            frozen_totals           JSONB        NOT NULL,
            notes                   VARCHAR(2000),
            CONSTRAINT chk_report_snapshots_kind
                CHECK (snapshot_kind IN ('CSRD_FINAL','EU_ETS_FINAL','INTERIM')),
            CONSTRAINT ux_report_snapshots_natural_key
                UNIQUE (tenant_id, anno, snapshot_kind, taken_at)
        );
        """
    )

    # Lookup index: list snapshots for tenant + year, newest first.
    op.execute(
        """
        CREATE INDEX ix_report_snapshots_tenant_anno
            ON calc.report_snapshots (tenant_id, anno, taken_at DESC);
        """
    )

    # Trace by correlation_id (links snapshot back to the calc run).
    op.execute(
        """
        CREATE INDEX ix_report_snapshots_correlation
            ON calc.report_snapshots (snapshot_correlation_id);
        """
    )

    # Append-only trigger - reuse the generic ops.deny_mutation defined in M0.
    op.execute(
        """
        CREATE TRIGGER trg_report_snapshots_deny_mutation
        BEFORE UPDATE OR DELETE ON calc.report_snapshots
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )

    # RLS: tenant isolation + esg_manager-only insert.
    op.execute("ALTER TABLE calc.report_snapshots ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE calc.report_snapshots FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY p_report_snapshots_select ON calc.report_snapshots
        FOR SELECT
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_report_snapshots_insert ON calc.report_snapshots
        FOR INSERT
        WITH CHECK (current_setting('app.role_code', true) = 'esg_manager'
                    AND tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )


def downgrade() -> None:
    """Drop calc.report_snapshots and its policies / trigger."""
    op.execute(
        "DROP POLICY IF EXISTS p_report_snapshots_insert ON calc.report_snapshots;"
    )
    op.execute(
        "DROP POLICY IF EXISTS p_report_snapshots_select ON calc.report_snapshots;"
    )
    op.execute("ALTER TABLE calc.report_snapshots DISABLE ROW LEVEL SECURITY;")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_report_snapshots_deny_mutation "
        "ON calc.report_snapshots;"
    )
    op.execute("DROP INDEX IF EXISTS calc.ix_report_snapshots_correlation;")
    op.execute("DROP INDEX IF EXISTS calc.ix_report_snapshots_tenant_anno;")
    op.execute("DROP TABLE IF EXISTS calc.report_snapshots;")
