"""M3 — DQ findings and DLQ tables (append-only).

Creates calc.dq_findings and calc.dlq per data_quality_report.md §13.1/§13.2
and architecture.md §4.3.  Both tables are append-only; resolution writes new
rows linked via parent_finding_id.

Revision: 0004_M3
Revises: 0003_M2
"""

from __future__ import annotations

from alembic import op

revision: str = "0004_M3"
down_revision: str = "0003_M2"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create calc.dq_findings and calc.dlq with append-only triggers."""

    # -- calc.dq_findings -----------------------------------------------------
    op.execute(
        """
        CREATE TABLE calc.dq_findings (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID         NOT NULL REFERENCES ref.tenants(id),
            correlation_id        UUID         NOT NULL,
            parent_finding_id     UUID REFERENCES calc.dq_findings(id),
            rule_id               VARCHAR(40)  NOT NULL,
            severity              VARCHAR(10)  NOT NULL
                                  CHECK (severity IN ('CRIT','WARN','INFO')),
            scope                 SMALLINT,
            codice_sito           VARCHAR(40),
            anno                  INT,
            metric                VARCHAR(100),
            value_observed        NUMERIC(20,6),
            value_reference       NUMERIC(20,6),
            ratio_yoy             NUMERIC(20,6),
            z_score               NUMERIC(20,6),
            trigger_desc          TEXT,
            recommended_action    TEXT,
            raw_row_id            UUID,
            blocks_pipeline       BOOLEAN      NOT NULL DEFAULT FALSE,
            dq_report_version     VARCHAR(40)  NOT NULL,
            assessed_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
            resolution_status     VARCHAR(20)  NOT NULL DEFAULT 'OPEN'
                                  CHECK (resolution_status IN ('OPEN','WAIVED','REMEDIATED')),
            waiver_reason_code    VARCHAR(40),
            waiver_justification  TEXT,
            waiver_approved_by    VARCHAR(120),
            resolved_at           TIMESTAMPTZ
        );
        CREATE INDEX ix_dq_findings_rule_sev
            ON calc.dq_findings(tenant_id, rule_id, severity);
        CREATE INDEX ix_dq_findings_correlation
            ON calc.dq_findings(correlation_id);
        CREATE INDEX ix_dq_findings_unresolved
            ON calc.dq_findings(tenant_id)
            WHERE resolution_status = 'OPEN';
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dq_findings_deny_mutation
        BEFORE UPDATE OR DELETE ON calc.dq_findings
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )

    # -- calc.dlq (Dead Letter Queue) ----------------------------------------
    op.execute(
        """
        CREATE TABLE calc.dlq (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID         NOT NULL REFERENCES ref.tenants(id),
            correlation_id        UUID         NOT NULL,
            dq_finding_id         UUID REFERENCES calc.dq_findings(id),
            rule_id               VARCHAR(40)  NOT NULL,
            severity              VARCHAR(10)  NOT NULL CHECK (severity IN ('CRIT','WARN')),
            scope                 SMALLINT     NOT NULL,
            codice_sito           VARCHAR(40),
            anno                  INT,
            combustibile_or_voce  VARCHAR(60),
            raw_row_payload       JSONB        NOT NULL,
            value_observed        NUMERIC(20,6),
            threshold             VARCHAR(120),
            z_score               NUMERIC(20,6),
            ratio_yoy             NUMERIC(20,6),
            fired_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            message               TEXT         NOT NULL,
            replay_status         VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                                  CHECK (replay_status IN ('PENDING','REPLAYED','ABANDONED')),
            replayed_at           TIMESTAMPTZ,
            replayed_by           VARCHAR(120)
        );
        CREATE INDEX ix_dlq_correlation ON calc.dlq(correlation_id);
        CREATE INDEX ix_dlq_unresolved  ON calc.dlq(tenant_id)
            WHERE replay_status = 'PENDING';
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dlq_deny_mutation
        BEFORE UPDATE OR DELETE ON calc.dlq
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )


def downgrade() -> None:
    """Reverse M3."""
    op.execute("DROP TABLE IF EXISTS calc.dlq CASCADE;")
    op.execute("DROP TABLE IF EXISTS calc.dq_findings CASCADE;")
