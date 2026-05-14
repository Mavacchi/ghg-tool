"""M5 — Materialised views and audit trail view.

Creates:
  - mv.mv_kpi_summary: materialised view for Streamlit KPI home page (NFR-02)
  - mv.v_audit_trail: join view emissions ← factor ← raw rows (FR-22, /audit-trail)
  - ops.refresh_mv_kpi_summary(): helper function for ETL runner
  - mv schema already created in M0; GO certificate QC view already in M0.

Revision: 0006_M5
Revises: 0005_M4
"""

from __future__ import annotations

from alembic import op

revision: str = "0006_M5"
down_revision: str = "0005_M4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create mv.mv_kpi_summary and mv.v_audit_trail."""

    # -- mv.mv_kpi_summary (materialised) ------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv.mv_kpi_summary AS
        SELECT
            e.tenant_id,
            e.regulatory_stream,
            e.gwp_set,
            e.anno,
            e.scope,
            e.sub_scope,
            e.codice_sito,
            SUM(e.tco2e)            AS tco2e_total,
            SUM(e.co2_biogenic_tonne) AS co2_biogenic_total,
            SUM(e.co2_fossil_tonne)   AS co2_fossil_total,
            COUNT(*)                AS row_count,
            MAX(e.calc_timestamp)   AS last_calc_at
        FROM calc.emissions_consolidated e
        WHERE e.valid_to IS NULL
        GROUP BY
            e.tenant_id, e.regulatory_stream, e.gwp_set,
            e.anno, e.scope, e.sub_scope, e.codice_sito;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_mv_kpi_summary
            ON mv.mv_kpi_summary(
                tenant_id, regulatory_stream, gwp_set,
                anno, scope, sub_scope,
                COALESCE(codice_sito, '')
            );
        """
    )

    # -- mv.v_audit_trail (regular view — always fresh) ----------------------
    op.execute(
        """
        CREATE OR REPLACE VIEW mv.v_audit_trail AS
        SELECT
            e.id                        AS emission_id,
            e.tenant_id,
            e.correlation_id,
            e.scope,
            e.sub_scope,
            e.codice_sito,
            e.anno,
            e.tco2e,
            e.co2_tonne,
            e.ch4_tco2e,
            e.n2o_tco2e,
            e.co2_biogenic_tonne,
            e.co2_fossil_tonne,
            e.gwp_set,
            e.regulatory_stream,
            e.methodology,
            e.calc_timestamp,
            e.created_by,
            e.valid_from,
            e.valid_to,
            e.superseded_by,
            e.reason_code,
            e.disclosure_notes,
            f.factor_id     AS factor_id_code,
            f.version       AS factor_version,
            f.source        AS factor_source,
            f.value         AS factor_value,
            f.unit          AS factor_unit,
            f.vintage       AS factor_vintage,
            f.pdf_source_uri AS factor_source_pdf,
            CASE e.raw_scope
                WHEN 1 THEN
                    (SELECT row_to_json(r1.*)
                     FROM raw.scope1_ingestions r1
                     WHERE r1.id = e.raw_row_id)
                WHEN 2 THEN
                    (SELECT row_to_json(r2.*)
                     FROM raw.scope2_ingestions r2
                     WHERE r2.id = e.raw_row_id)
                WHEN 3 THEN
                    (SELECT row_to_json(r3.*)
                     FROM raw.scope3_ingestions r3
                     WHERE r3.id = e.raw_row_id)
            END AS raw_row_json
        FROM calc.emissions_consolidated e
        JOIN ref.factor_catalog f ON f.id = e.factor_id;
        """
    )

    # -- ops.refresh_mv_kpi_summary() convenience function -------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.refresh_mv_kpi_summary()
        RETURNS VOID AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY mv.mv_kpi_summary;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    """Reverse M5."""
    op.execute("DROP FUNCTION IF EXISTS ops.refresh_mv_kpi_summary() CASCADE;")
    op.execute("DROP VIEW IF EXISTS mv.v_audit_trail CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv.mv_kpi_summary CASCADE;")
