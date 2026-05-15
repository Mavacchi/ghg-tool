"""M24 — Rename application roles to generic labels.

Maps domain-specific role_codes to generic, familiar names:
  esg_manager  -> admin
  data_steward -> editor
  auditor      -> viewer

Rationale: user requested generic role labels (admin/editor/viewer) instead of
domain-specific ones. Separation-of-duties per ISAE 3000 §A99 is preserved — only
the labels change. Pre-M24 deployments used esg_manager/data_steward/auditor (1:1
mapping).

RLS policies in M4 (0005_M4_rls_policies.py), M6 (0007_M6_intensity_mv.py) and M13
(0012_M13_report_snapshots.py) reference the old role_code strings in their
USING / WITH CHECK clauses. This migration drops and recreates those policies with
updated role strings. The policy names stay the same so that M4's downgrade() can
still reference them if a full rollback is ever executed.

Affected policies (role_code references only — tenant_id / SELECT policies unchanged):
  calc.emissions_consolidated : p_emissions_auditor_select, p_emissions_steward_insert
  raw.scope1_ingestions       : p_raw_scope1_ingestions_insert
  raw.scope2_ingestions       : p_raw_scope2_ingestions_insert
  raw.scope3_ingestions       : p_raw_scope3_ingestions_insert
  raw.ingestion_batches       : p_raw_ingestion_batches_insert
  ref.factor_catalog          : p_factor_insert_steward
  ref.go_certificate_evidence : p_go_insert_steward
  raw.intensity_references    : p_raw_intensity_references_insert (M6)
  calc.dq_findings            : p_dq_insert
  calc.dlq                    : p_dlq_insert
  calc.report_snapshots       : p_report_snapshots_insert (M13)

NOTE: This migration deliberately does NOT touch previous migration files. Migration
history is immutable; retroactive edits are forbidden.

Revision ID : 0025_M24
Revises     : 0024_M23
Create Date : 2026-05-15
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

# ---------------------------------------------------------------------------
revision: str = "0025_M24"
down_revision: str = "0024_M23"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Rename role_codes in ref.roles and update RLS policies to new names."""

    # -----------------------------------------------------------------------
    # 1. Rename role_codes and update descriptions in ref.roles
    # -----------------------------------------------------------------------

    op.execute(
        text(
            "UPDATE ref.roles "
            "SET role_code = 'admin', "
            "    description = 'Approves reports, signs off CSRD disclosure, "
            "manages factor catalog publish workflow' "
            "WHERE role_code = 'esg_manager'"
        )
    )

    op.execute(
        text(
            "UPDATE ref.roles "
            "SET role_code = 'editor', "
            "    description = 'Inputs and corrects data; manages factor catalog drafts' "
            "WHERE role_code = 'data_steward'"
        )
    )

    op.execute(
        text(
            "UPDATE ref.roles "
            "SET role_code = 'viewer', "
            "    description = "
            "'Read-only review — ISAE 3000 Limited assurance provider' "
            "WHERE role_code = 'auditor'"
        )
    )

    # -----------------------------------------------------------------------
    # 2. Update RLS policies that hard-code old role_code strings
    #    Drop → recreate with same policy name so M4 downgrade() still works.
    # -----------------------------------------------------------------------

    # -- calc.emissions_consolidated: SELECT (auditor|esg_manager|data_steward) --
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_emissions_auditor_select "
            "ON calc.emissions_consolidated"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_emissions_auditor_select
                ON calc.emissions_consolidated
                FOR SELECT
                USING (
                    current_setting('app.role_code', true)
                        IN ('viewer', 'admin', 'editor')
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- calc.emissions_consolidated: INSERT (data_steward|esg_manager) ----------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_emissions_steward_insert "
            "ON calc.emissions_consolidated"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_emissions_steward_insert
                ON calc.emissions_consolidated
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true)
                        IN ('editor', 'admin')
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.scope1_ingestions: INSERT (data_steward) ----------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_scope1_ingestions_insert "
            "ON raw.scope1_ingestions"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_scope1_ingestions_insert
                ON raw.scope1_ingestions
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'editor'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.scope2_ingestions: INSERT (data_steward) ----------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_scope2_ingestions_insert "
            "ON raw.scope2_ingestions"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_scope2_ingestions_insert
                ON raw.scope2_ingestions
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'editor'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.scope3_ingestions: INSERT (data_steward) ----------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_scope3_ingestions_insert "
            "ON raw.scope3_ingestions"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_scope3_ingestions_insert
                ON raw.scope3_ingestions
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'editor'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.ingestion_batches: INSERT (data_steward) ----------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_ingestion_batches_insert "
            "ON raw.ingestion_batches"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_ingestion_batches_insert
                ON raw.ingestion_batches
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'editor'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- ref.factor_catalog: INSERT (data_steward) -------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_factor_insert_steward "
            "ON ref.factor_catalog"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_factor_insert_steward
                ON ref.factor_catalog
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'editor'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- ref.go_certificate_evidence: INSERT (data_steward) ----------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_go_insert_steward "
            "ON ref.go_certificate_evidence"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_go_insert_steward
                ON ref.go_certificate_evidence
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'editor'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.intensity_references: INSERT (data_steward) — added in M6 ----------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_intensity_references_insert "
            "ON raw.intensity_references"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_intensity_references_insert
                ON raw.intensity_references
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'editor'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- calc.dq_findings: INSERT (data_steward|esg_manager) ---------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_dq_insert ON calc.dq_findings"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_dq_insert
                ON calc.dq_findings
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true)
                        IN ('editor', 'admin')
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- calc.dlq: INSERT (data_steward) -----------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_dlq_insert ON calc.dlq"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_dlq_insert
                ON calc.dlq
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'editor'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- calc.report_snapshots: INSERT (esg_manager) — added in M13 --------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_report_snapshots_insert "
            "ON calc.report_snapshots"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_report_snapshots_insert
                ON calc.report_snapshots
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'admin'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )


def downgrade() -> None:
    """Revert role_codes in ref.roles and restore original RLS policies."""

    # -----------------------------------------------------------------------
    # 1. Revert role_codes and descriptions (symmetric reverse)
    # -----------------------------------------------------------------------

    op.execute(
        text(
            "UPDATE ref.roles "
            "SET role_code = 'esg_manager', "
            "    description = 'Approves reports, signs off CSRD disclosure, "
            "waives DQ-WARN' "
            "WHERE role_code = 'admin'"
        )
    )

    op.execute(
        text(
            "UPDATE ref.roles "
            "SET role_code = 'data_steward', "
            "    description = "
            "'Inputs and validates raw activity data; manages factor catalog' "
            "WHERE role_code = 'editor'"
        )
    )

    op.execute(
        text(
            "UPDATE ref.roles "
            "SET role_code = 'auditor', "
            "    description = "
            "'Read-only review — ISAE 3000 Limited assurance provider' "
            "WHERE role_code = 'viewer'"
        )
    )

    # -----------------------------------------------------------------------
    # 2. Restore original RLS policies with old role_code strings
    # -----------------------------------------------------------------------

    # -- calc.emissions_consolidated: SELECT ------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_emissions_auditor_select "
            "ON calc.emissions_consolidated"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_emissions_auditor_select
                ON calc.emissions_consolidated
                FOR SELECT
                USING (
                    current_setting('app.role_code', true)
                        IN ('auditor', 'esg_manager', 'data_steward')
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- calc.emissions_consolidated: INSERT ------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_emissions_steward_insert "
            "ON calc.emissions_consolidated"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_emissions_steward_insert
                ON calc.emissions_consolidated
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true)
                        IN ('data_steward', 'esg_manager')
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.scope1_ingestions: INSERT ------------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_scope1_ingestions_insert "
            "ON raw.scope1_ingestions"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_scope1_ingestions_insert
                ON raw.scope1_ingestions
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.scope2_ingestions: INSERT ------------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_scope2_ingestions_insert "
            "ON raw.scope2_ingestions"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_scope2_ingestions_insert
                ON raw.scope2_ingestions
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.scope3_ingestions: INSERT ------------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_scope3_ingestions_insert "
            "ON raw.scope3_ingestions"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_scope3_ingestions_insert
                ON raw.scope3_ingestions
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.ingestion_batches: INSERT ------------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_ingestion_batches_insert "
            "ON raw.ingestion_batches"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_ingestion_batches_insert
                ON raw.ingestion_batches
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- ref.factor_catalog: INSERT ---------------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_factor_insert_steward "
            "ON ref.factor_catalog"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_factor_insert_steward
                ON ref.factor_catalog
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- ref.go_certificate_evidence: INSERT ------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_go_insert_steward "
            "ON ref.go_certificate_evidence"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_go_insert_steward
                ON ref.go_certificate_evidence
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- raw.intensity_references: INSERT (M6) ----------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_raw_intensity_references_insert "
            "ON raw.intensity_references"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_raw_intensity_references_insert
                ON raw.intensity_references
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- calc.dq_findings: INSERT -----------------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_dq_insert ON calc.dq_findings"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_dq_insert
                ON calc.dq_findings
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true)
                        IN ('data_steward', 'esg_manager')
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- calc.dlq: INSERT -------------------------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_dlq_insert ON calc.dlq"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_dlq_insert
                ON calc.dlq
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'data_steward'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )

    # -- calc.report_snapshots: INSERT (M13) ------------------------------------
    op.execute(
        text(
            "DROP POLICY IF EXISTS p_report_snapshots_insert "
            "ON calc.report_snapshots"
        )
    )
    op.execute(
        text(
            """
            CREATE POLICY p_report_snapshots_insert
                ON calc.report_snapshots
                FOR INSERT
                WITH CHECK (
                    current_setting('app.role_code', true) = 'esg_manager'
                    AND tenant_id =
                        current_setting('app.tenant_id', true)::uuid
                )
            """
        )
    )
