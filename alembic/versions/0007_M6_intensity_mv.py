"""M6 — Intensity materialised view + schema-name reconciliation.

DECISIONS DOCUMENTED
====================

Decision 1 — Schema reconciliation (calc vs mv)
------------------------------------------------
M5 created ``mv.mv_kpi_summary`` but both routers already query ``calc.*``.

Option A selected: drop ``mv.mv_kpi_summary``, recreate as ``calc.mv_kpi_summary``.
Rationale: M0 schema intention is "calc = computed/derived results".  ``mv`` was
introduced in M5 without updating the routers.  Moving the MV to ``calc`` fixes
the mismatch at the SQL layer with zero Python-code changes.  Options B and C
were rejected: B requires touching three Python files; C adds indirection with no
benefit (a non-materialised VIEW over a materialised VIEW still doesn't let REFRESH
CONCURRENTLY work on the outer view).

Secondary fix: M5's SELECT exposed the year column as ``anno``, but
``kpis.py`` line 72 filters on ``reporting_year = :anno``.  The new MV aliases
``e.anno AS reporting_year`` so the router filter resolves.

Decision 2 — Intensity denominator table
-----------------------------------------
No ``raw.intensity_references`` (or any equivalent) exists in M0–M5.
Long format created here: one row per (tenant_id, codice_sito, anno, denominator_type).
Long format preferred over wide: adding a fifth denominator type in a future
migration is a data INSERT, not an ALTER TABLE.

All four denominator types required by FR-26 / router:
  EUR_revenue   — tCO2e per EUR revenue
  m2_production — tCO2e per m² production area
  FTE           — tCO2e per full-time-equivalent headcount (REV-017)
  kg_product    — tCO2e per kg product (tonne basis in source data)

RLS on raw.intensity_references follows the M4 pattern: all roles SELECT,
data_steward INSERT only.

OBJECTS CREATED
===============
  calc.mv_kpi_summary            (re-created from mv.mv_kpi_summary)
  calc.mv_intensity_metrics      (new)
  raw.intensity_references       (new)
  ux_mv_kpi_summary              (unique index on calc.mv_kpi_summary)
  ux_mv_intensity_metrics        (unique index on calc.mv_intensity_metrics)
  ix_intensity_references_tenant_year
  ops.refresh_mv_kpi_summary()   (re-created pointing to calc.*)
  ops.refresh_mv_intensity_metrics()
  ops.refresh_all_materialised_views()

OBJECTS DROPPED IN UPGRADE
===========================
  mv.mv_kpi_summary              (old, schema-mismatch version from M5)
  ops.refresh_mv_kpi_summary()   (old version pointing to mv.*)

DOWNGRADE
=========
Drops everything M6 added, then re-creates M5's state:
  mv.mv_kpi_summary + ops.refresh_mv_kpi_summary() pointing to mv.*
  raw.intensity_references CASCADE
  calc.mv_intensity_metrics CASCADE

Revision: 0007_M6
Revises: 0006_M5
"""

from __future__ import annotations

from alembic import op

revision: str = "0007_M6"
down_revision: str = "0006_M5"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply M6: schema reconciliation + intensity MV + denominator table."""

    # -------------------------------------------------------------------------
    # Step 1 — Drop old mv.mv_kpi_summary (M5 artefact, wrong schema)
    # -------------------------------------------------------------------------
    # Drop dependent function first to avoid "is still referenced" errors.
    op.execute("DROP FUNCTION IF EXISTS ops.refresh_mv_kpi_summary() CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv.mv_kpi_summary CASCADE;")

    # -------------------------------------------------------------------------
    # Step 2 — Recreate mv_kpi_summary in calc schema
    #
    # Column alias: e.anno AS reporting_year
    #   kpis.py line 72 filters on "reporting_year = :anno"; M5 had the column
    #   named "anno" which caused every kpis query to return 0 rows (column not
    #   found in the WHERE clause, SQLAlchemy raises ProgrammingError → stub).
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW calc.mv_kpi_summary AS
        SELECT
            e.tenant_id,
            e.regulatory_stream,
            e.gwp_set,
            e.anno                    AS reporting_year,
            e.scope,
            e.sub_scope,
            e.codice_sito,
            SUM(e.tco2e)              AS tco2e_total,
            SUM(e.co2_biogenic_tonne) AS co2_biogenic_total,
            SUM(e.co2_fossil_tonne)   AS co2_fossil_total,
            COUNT(*)                  AS row_count,
            MAX(e.calc_timestamp)     AS last_calc_at
        FROM calc.emissions_consolidated e
        WHERE e.valid_to IS NULL
        GROUP BY
            e.tenant_id, e.regulatory_stream, e.gwp_set,
            e.anno, e.scope, e.sub_scope, e.codice_sito;
        """
    )

    # UNIQUE INDEX required for REFRESH CONCURRENTLY.
    # COALESCE handles NULL codice_sito (company-wide rows) — compatible with
    # PostgreSQL 14 which lacks NULLS NOT DISTINCT on indexes.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_mv_kpi_summary
            ON calc.mv_kpi_summary(
                tenant_id, regulatory_stream, gwp_set,
                reporting_year, scope, sub_scope,
                COALESCE(codice_sito, '')
            );
        """
    )

    # Refresh function — now references calc schema
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.refresh_mv_kpi_summary()
        RETURNS VOID AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY calc.mv_kpi_summary;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # -------------------------------------------------------------------------
    # Step 3 — Create raw.intensity_references (long format)
    #
    # NULL codice_sito = company-wide denominator (applies to all sites in the
    # JOIN below when no site-specific row exists).
    # CHECK: FTE rows must carry hr_confirmation_date (REV-017 audit trail).
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.intensity_references (
            id                   BIGSERIAL    PRIMARY KEY,
            tenant_id            UUID         NOT NULL REFERENCES ref.tenants(id),
            codice_sito          VARCHAR(40),
            anno                 SMALLINT     NOT NULL,
            denominator_type     TEXT         NOT NULL
                                 CHECK (denominator_type IN
                                        ('EUR_revenue', 'm2_production', 'FTE', 'kg_product')),
            denominator_value    NUMERIC(18,4) NOT NULL CHECK (denominator_value > 0),
            denominator_unit     TEXT         NOT NULL,
            hr_confirmation_date DATE,
            source_document      TEXT,
            inserted_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            inserted_by          TEXT         NOT NULL,
            CONSTRAINT chk_fte_requires_hr_date
                CHECK (denominator_type <> 'FTE' OR hr_confirmation_date IS NOT NULL)
        );
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_intensity_references_tenant_year
            ON raw.intensity_references(tenant_id, anno);
        """
    )

    # RLS — mirror M4 pattern for raw.* tables: all roles SELECT, steward INSERT
    op.execute(
        "ALTER TABLE raw.intensity_references ENABLE ROW LEVEL SECURITY;"
    )
    op.execute(
        "ALTER TABLE raw.intensity_references FORCE ROW LEVEL SECURITY;"
    )
    op.execute(
        """
        CREATE POLICY p_raw_intensity_references_select
            ON raw.intensity_references
            FOR SELECT
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )
    op.execute(
        """
        CREATE POLICY p_raw_intensity_references_insert
            ON raw.intensity_references
            FOR INSERT
            WITH CHECK (
                current_setting('app.role_code', true) = 'data_steward'
                AND tenant_id = current_setting('app.tenant_id', true)::uuid
            );
        """
    )

    # Append-only guard consistent with raw.scope*_ingestions
    op.execute(
        """
        CREATE TRIGGER trg_raw_intensity_references_deny_mutation
        BEFORE UPDATE OR DELETE ON raw.intensity_references
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )

    # -------------------------------------------------------------------------
    # Step 4 — Create calc.mv_intensity_metrics
    #
    # Column contract (must match intensity.py line 173–179 SELECT exactly):
    #   anno, codice_sito, scope_label, intensity_value, denominator_value,
    #   denominator_unit, gwp_set, factor_source, factor_version, methodology,
    #   hr_confirmation_date, confidence_interval_lower, confidence_interval_upper,
    #   correlation_id
    #
    # Additional columns needed by the unique index (not SELECTed by the router
    # but required for CONCURRENTLY refresh):
    #   tenant_id, denominator_type
    #
    # scope_label values match IntensityRow Literal:
    #   'Scope1', 'Scope2_LB', 'Scope2_MB', 'Scope3', 'Total'
    #
    # correlation_id cast to TEXT because IntensityRow.correlation_id: str
    # and router builds IntensityRow(**r) directly from the dict.
    #
    # confidence_interval_lower / confidence_interval_upper: NULL in the MV
    # per spec — CI computation is a DataAnalyst service concern, not ETL.
    # IntensityRow fields are Optional[Decimal] so NULL is accepted.
    #
    # Provenance aggregation uses array_agg ... ORDER BY calc_timestamp DESC
    # to pick the most-recent value deterministically rather than relying on
    # arbitrary aggregation order.
    #
    # JOIN condition: denominator row matches on (tenant_id, anno) and either
    # site-specific (r.codice_sito = e.codice_sito) or company-wide (r.codice_sito
    # IS NULL).  Site-specific rows take precedence via the DISTINCT ON outer
    # query to avoid double-counting when both exist for the same site+year.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW calc.mv_intensity_metrics AS
        WITH emissions_by_scope AS (
            SELECT
                e.tenant_id,
                e.anno,
                e.codice_sito,
                e.gwp_set,
                CASE
                    WHEN e.scope = 1                         THEN 'Scope1'
                    WHEN e.scope = 2 AND e.sub_scope = 'LB' THEN 'Scope2_LB'
                    WHEN e.scope = 2 AND e.sub_scope = 'MB' THEN 'Scope2_MB'
                    WHEN e.scope = 3                         THEN 'Scope3'
                END AS scope_label,
                SUM(e.tco2e)                                                          AS tco2e_total,
                (array_agg(e.factor_source  ORDER BY e.calc_timestamp DESC))[1]       AS factor_source,
                (array_agg(e.factor_version ORDER BY e.calc_timestamp DESC))[1]       AS factor_version,
                (array_agg(e.methodology    ORDER BY e.calc_timestamp DESC))[1]       AS methodology,
                MAX(e.calc_timestamp)                                                  AS last_calc_at,
                (MAX(e.correlation_id::text))                                          AS correlation_id
            FROM calc.emissions_consolidated e
            WHERE e.valid_to IS NULL
            GROUP BY
                e.tenant_id, e.anno, e.codice_sito, e.gwp_set,
                CASE
                    WHEN e.scope = 1                         THEN 'Scope1'
                    WHEN e.scope = 2 AND e.sub_scope = 'LB' THEN 'Scope2_LB'
                    WHEN e.scope = 2 AND e.sub_scope = 'MB' THEN 'Scope2_MB'
                    WHEN e.scope = 3                         THEN 'Scope3'
                END
        ),
        scope_totals AS (
            -- "Total" pseudo-scope: sum of all per-scope rows for the same
            -- (tenant, anno, site, gwp_set).  Scope2_LB and Scope2_MB are
            -- mutually exclusive in practice (a given run uses one variant),
            -- but both may exist in the table when both regulatory streams are
            -- calculated.  We sum whatever is present — the router always
            -- filters by a single denominator_type which aligns to one variant.
            SELECT
                tenant_id,
                anno,
                codice_sito,
                gwp_set,
                'Total'                                          AS scope_label,
                SUM(tco2e_total)                                 AS tco2e_total,
                (array_agg(factor_source))[1]                    AS factor_source,
                (array_agg(factor_version))[1]                   AS factor_version,
                'sum-of-scopes'                                  AS methodology,
                MAX(last_calc_at)                                AS last_calc_at,
                MAX(correlation_id)                              AS correlation_id
            FROM emissions_by_scope
            GROUP BY tenant_id, anno, codice_sito, gwp_set
        ),
        all_scopes AS (
            SELECT * FROM emissions_by_scope
            UNION ALL
            SELECT * FROM scope_totals
        ),
        -- Resolve denominator: prefer site-specific row over company-wide NULL.
        -- DISTINCT ON keeps the first row per (tenant, anno, site, gwp, scope,
        -- denom_type) after ordering site-specific rows first.
        resolved_denominators AS (
            SELECT DISTINCT ON (
                e.tenant_id, e.anno, e.codice_sito, e.gwp_set,
                e.scope_label, r.denominator_type
            )
                e.tenant_id,
                e.anno,
                e.codice_sito,
                e.gwp_set,
                e.scope_label,
                e.tco2e_total,
                e.factor_source,
                e.factor_version,
                e.methodology,
                e.last_calc_at,
                e.correlation_id,
                r.denominator_type,
                r.denominator_value,
                r.denominator_unit,
                r.hr_confirmation_date
            FROM all_scopes e
            JOIN raw.intensity_references r
                ON  r.tenant_id = e.tenant_id
                AND r.anno      = e.anno
                AND (r.codice_sito = e.codice_sito OR r.codice_sito IS NULL)
            WHERE r.denominator_value > 0
            -- Site-specific rows (r.codice_sito IS NOT NULL) before fallback
            ORDER BY
                e.tenant_id, e.anno, e.codice_sito, e.gwp_set,
                e.scope_label, r.denominator_type,
                (r.codice_sito IS NULL) ASC
        )
        SELECT
            tenant_id,
            anno,
            codice_sito,
            scope_label,
            gwp_set,
            denominator_type,
            denominator_value,
            denominator_unit,
            -- Intensity ratio: tCO2e per denominator unit (FR-26)
            (tco2e_total / denominator_value)::NUMERIC(20, 8)   AS intensity_value,
            factor_source,
            factor_version,
            methodology,
            hr_confirmation_date,
            -- Bootstrap CI bounds: NULL — computed by DataAnalyst service on demand
            NULL::NUMERIC(20, 8)                                 AS confidence_interval_lower,
            NULL::NUMERIC(20, 8)                                 AS confidence_interval_upper,
            last_calc_at,
            correlation_id
        FROM resolved_denominators;
        """
    )

    # -------------------------------------------------------------------------
    # Step 5 — Unique index on calc.mv_intensity_metrics
    #
    # Required by REFRESH MATERIALIZED VIEW CONCURRENTLY.
    # COALESCE(codice_sito, '__GLOBAL__') handles NULL codice_sito on PostgreSQL
    # <15 (NULLS NOT DISTINCT not available before PG15).
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX ux_mv_intensity_metrics
            ON calc.mv_intensity_metrics(
                tenant_id,
                anno,
                COALESCE(codice_sito, '__GLOBAL__'),
                scope_label,
                gwp_set,
                denominator_type
            );
        """
    )

    # -------------------------------------------------------------------------
    # Step 6 — Refresh functions
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.refresh_mv_intensity_metrics()
        RETURNS VOID AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY calc.mv_intensity_metrics;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.refresh_all_materialised_views()
        RETURNS VOID AS $$
        BEGIN
            PERFORM ops.refresh_mv_kpi_summary();
            PERFORM ops.refresh_mv_intensity_metrics();
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    """Reverse M6 — restore state to end of M5.

    Order:
      1. Drop M6 refresh functions (intensity + combined).
      2. Drop calc.mv_intensity_metrics + its index.
      3. Drop RLS policies + trigger + table for raw.intensity_references.
      4. Drop calc.mv_kpi_summary (M6 version in calc schema).
      5. Drop M6's ops.refresh_mv_kpi_summary (calc-schema version).
      6. Recreate M5's mv.mv_kpi_summary + index + refresh function (mv schema).
    """

    # -- 1. Drop M6 refresh functions -----------------------------------------
    op.execute("DROP FUNCTION IF EXISTS ops.refresh_all_materialised_views() CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS ops.refresh_mv_intensity_metrics() CASCADE;")

    # -- 2. Drop calc.mv_intensity_metrics ------------------------------------
    op.execute("DROP MATERIALIZED VIEW IF EXISTS calc.mv_intensity_metrics CASCADE;")

    # -- 3. Drop raw.intensity_references (M6 created it; safe to drop) -------
    # Policies and trigger are dropped automatically via CASCADE.
    op.execute("DROP TABLE IF EXISTS raw.intensity_references CASCADE;")

    # -- 4 & 5. Drop calc.mv_kpi_summary + its refresh function ---------------
    op.execute("DROP FUNCTION IF EXISTS ops.refresh_mv_kpi_summary() CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS calc.mv_kpi_summary CASCADE;")

    # -- 6. Restore M5 state: mv.mv_kpi_summary in original mv schema ---------
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
            SUM(e.tco2e)              AS tco2e_total,
            SUM(e.co2_biogenic_tonne) AS co2_biogenic_total,
            SUM(e.co2_fossil_tonne)   AS co2_fossil_total,
            COUNT(*)                  AS row_count,
            MAX(e.calc_timestamp)     AS last_calc_at
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
