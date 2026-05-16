"""M4 — Row-Level Security policies for all three RBAC roles.

Creates PostgreSQL RLS policies per architecture.md §5.  Session GUCs
``app.tenant_id`` and ``app.role_code`` are set by the application layer
(infrastructure/db/session.py) on every connection before any SQL runs.

Single-tenant v1: tenant_id column present on every table for future
multi-tenant isolation without re-migration (AD-007).

Revision: 0005_M4
Revises: 0004_M3
"""

from __future__ import annotations

from alembic import op

revision: str = "0005_M4"
down_revision: str = "0004_M3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Enable RLS and create all policies for the 3 RBAC roles."""

    # -- Enable RLS on all tenant-scoped tables --------------------------------
    tables_rls = [
        "raw.scope1_ingestions",
        "raw.scope2_ingestions",
        "raw.scope3_ingestions",
        "raw.ingestion_batches",
        "ref.factor_catalog",
        "ref.go_certificate_evidence",
        "calc.emissions_consolidated",
        "calc.dq_findings",
        "calc.dlq",
        "calc.audit_log",
    ]
    for tbl in tables_rls:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")

    # -- calc.emissions_consolidated ------------------------------------------
    op.execute(
        """
        CREATE POLICY p_emissions_tenant_isolation ON calc.emissions_consolidated
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_emissions_auditor_select ON calc.emissions_consolidated
        FOR SELECT
        USING (current_setting('app.role_code', true) IN ('auditor','esg_manager','data_steward')
               AND tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_emissions_steward_insert ON calc.emissions_consolidated
        FOR INSERT
        WITH CHECK (current_setting('app.role_code', true) IN ('data_steward','esg_manager')
                    AND tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -- raw tables: all roles SELECT; only data_steward INSERT ---------------
    for scope_tbl in ("raw.scope1_ingestions", "raw.scope2_ingestions",
                      "raw.scope3_ingestions", "raw.ingestion_batches"):
        short = scope_tbl.replace(".", "_")
        op.execute(
            f"""
            CREATE POLICY p_{short}_select ON {scope_tbl}
            FOR SELECT
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
            """
        )
        op.execute(
            f"""
            CREATE POLICY p_{short}_insert ON {scope_tbl}
            FOR INSERT
            WITH CHECK (current_setting('app.role_code', true) = 'data_steward'
                        AND tenant_id = current_setting('app.tenant_id', true)::uuid);
            """
        )

    # -- ref.factor_catalog ---------------------------------------------------
    op.execute(
        """
        CREATE POLICY p_factor_select_all ON ref.factor_catalog
        FOR SELECT
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_factor_insert_steward ON ref.factor_catalog
        FOR INSERT
        WITH CHECK (current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -- ref.go_certificate_evidence ------------------------------------------
    op.execute(
        """
        CREATE POLICY p_go_select ON ref.go_certificate_evidence
        FOR SELECT
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_go_insert_steward ON ref.go_certificate_evidence
        FOR INSERT
        WITH CHECK (current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -- calc.dq_findings -----------------------------------------------------
    op.execute(
        """
        CREATE POLICY p_dq_select_all ON calc.dq_findings
        FOR SELECT
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_dq_insert ON calc.dq_findings
        FOR INSERT
        WITH CHECK (current_setting('app.role_code', true) IN ('data_steward','esg_manager')
                    AND tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -- calc.dlq -------------------------------------------------------------
    op.execute(
        """
        CREATE POLICY p_dlq_select ON calc.dlq
        FOR SELECT
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_dlq_insert ON calc.dlq
        FOR INSERT
        WITH CHECK (current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -- calc.audit_log -------------------------------------------------------
    op.execute(
        """
        CREATE POLICY p_audit_select ON calc.audit_log
        FOR SELECT
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_audit_insert ON calc.audit_log
        FOR INSERT
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -- Column-level deny: password_hash not visible to auditor --------------
    op.execute(
        """
        REVOKE SELECT (password_hash) ON ref.users FROM PUBLIC;
        """
    )


def downgrade() -> None:
    """Drop all RLS policies and disable RLS on affected tables."""
    tables_rls = [
        "raw.scope1_ingestions", "raw.scope2_ingestions", "raw.scope3_ingestions",
        "raw.ingestion_batches", "ref.factor_catalog", "ref.go_certificate_evidence",
        "calc.emissions_consolidated", "calc.dq_findings", "calc.dlq", "calc.audit_log",
    ]
    policy_prefixes = [
        "p_emissions_tenant_isolation", "p_emissions_auditor_select",
        "p_emissions_steward_insert",
        "p_raw_scope1_ingestions_select", "p_raw_scope1_ingestions_insert",
        "p_raw_scope2_ingestions_select", "p_raw_scope2_ingestions_insert",
        "p_raw_scope3_ingestions_select", "p_raw_scope3_ingestions_insert",
        "p_raw_ingestion_batches_select", "p_raw_ingestion_batches_insert",
        "p_factor_select_all", "p_factor_insert_steward",
        "p_go_select", "p_go_insert_steward",
        "p_dq_select_all", "p_dq_insert",
        "p_dlq_select", "p_dlq_insert",
        "p_audit_select", "p_audit_insert",
    ]
    # Drop policies (table-agnostic: PostgreSQL will skip unknown ones)
    for tbl in tables_rls:
        for pol in policy_prefixes:
            op.execute(f"DROP POLICY IF EXISTS {pol} ON {tbl};")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;")
    # Restoring PUBLIC grant would expose password hashes to every DB role;
    # restrict to the application role only. PUBLIC access was never correct —
    # the original REVOKE in upgrade() was itself fixing an over-permissive
    # default.  Downgrade must not re-introduce the vulnerability.
    op.execute("GRANT SELECT (password_hash) ON ref.users TO ghg_app;")
