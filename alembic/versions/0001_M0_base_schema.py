"""M0 — Base schema: extensions, schemas, ops.deny_mutation, tenants, sites, roles, users,
gwp_sets (seeded AR6+AR5), ingestion_batches, raw staging tables, factor_catalog skeleton,
go_certificate_evidence.

ADR-007: co2_biogenic_tonne + co2_fossil_tonne columns present on emissions_consolidated
from the very first migration (applied in M1, seeded here for schema awareness).

Revision: 0001_M0
Revises: (none)
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0001_M0"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Create base schemas, extensions, shared mutation-guard function, and reference tables."""

    # -- Extensions -----------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements;")

    # -- Schemas --------------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS raw;")
    op.execute("CREATE SCHEMA IF NOT EXISTS ref;")
    op.execute("CREATE SCHEMA IF NOT EXISTS calc;")
    op.execute("CREATE SCHEMA IF NOT EXISTS mv;")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops;")

    # -- Shared append-only mutation guard (raw + audit + dq tables) ----------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.deny_mutation() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = 'P0001',
                MESSAGE = format(
                    'Mutation forbidden on append-only table %I.%I',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                );
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # -- ref.tenants ----------------------------------------------------------
    op.execute(
        """
        CREATE TABLE ref.tenants (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code         VARCHAR(40)  NOT NULL UNIQUE,
            legal_name   VARCHAR(200) NOT NULL,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        """
    )
    # v1 single-tenant seed
    op.execute(
        """
        INSERT INTO ref.tenants (code, legal_name)
        VALUES ('CERAMIC_TILE_CO', 'Ceramic Tile Manufacturer S.p.A.');
        """
    )

    # -- ref.roles ------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE ref.roles (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            role_code   VARCHAR(40) NOT NULL UNIQUE,
            description TEXT        NOT NULL
        );
        """
    )
    op.execute(
        """
        INSERT INTO ref.roles (role_code, description) VALUES
            ('data_steward', 'Inputs and validates raw activity data; manages factor catalog'),
            ('esg_manager',  'Approves reports, signs off CSRD disclosure, waives DQ-WARN'),
            ('auditor',      'Read-only review — ISAE 3000 Limited assurance provider');
        """
    )

    # -- ref.users ------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE ref.users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL REFERENCES ref.tenants(id),
            username        VARCHAR(120) NOT NULL,
            email           VARCHAR(200) NOT NULL,
            password_hash   VARCHAR(200) NOT NULL,
            role_id         UUID         NOT NULL REFERENCES ref.roles(id),
            is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            last_login_at   TIMESTAMPTZ,
            UNIQUE (tenant_id, username),
            UNIQUE (tenant_id, email)
        );
        """
    )

    # -- ref.sites (7 sites seeded per requirements.md §5.2) -----------------
    op.execute(
        """
        CREATE TABLE ref.sites (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id              UUID         NOT NULL REFERENCES ref.tenants(id),
            codice_sito            VARCHAR(40)  NOT NULL,
            full_name              VARCHAR(200) NOT NULL,
            role                   VARCHAR(80)  NOT NULL,
            geography              VARCHAR(40)  NOT NULL,
            eu_ets_installation_id VARCHAR(80),
            eu_ets_activity        VARCHAR(80),
            is_active              BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, codice_sito)
        );
        """
    )
    # Seed 7 sites — IANO carries EU ETS Annex I Activity 17 (OI-7 confirmed YES)
    op.execute(
        """
        INSERT INTO ref.sites (tenant_id, codice_sito, full_name, role, geography,
                               eu_ets_installation_id, eu_ets_activity)
        SELECT t.id,
               v.codice_sito, v.full_name, v.role, 'Italy',
               v.eu_ets_id, v.eu_ets_activity
        FROM ref.tenants t,
        (VALUES
            ('IANO',          'IANO Production Site',          'Main',      'IT-ETS-IANO-001', 'Annex I Activity 17'),
            ('VIANO',         'VIANO Production Site',         'Secondary', NULL,              NULL),
            ('VIANO_GARGOLA', 'VIANO_GARGOLA Production Site', 'Secondary', NULL,              NULL),
            ('CASALGRANDE',   'CASALGRANDE Production Site',   'Secondary', NULL,              NULL),
            ('FIORANO',       'FIORANO Production Site',       'Secondary', NULL,              NULL),
            ('SASSUOLO',      'SASSUOLO Production Site',      'Secondary', NULL,              NULL),
            ('FRASSINORO',    'FRASSINORO Production Site',    'Secondary', NULL,              NULL)
        ) AS v(codice_sito, full_name, role, eu_ets_id, eu_ets_activity)
        WHERE t.code = 'CERAMIC_TILE_CO';
        """
    )

    # -- ref.gwp_sets (seeded AR6 + AR5 per methodology_validation.md §11) ---
    op.execute(
        """
        CREATE TABLE ref.gwp_sets (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            gwp_set         VARCHAR(10)  NOT NULL CHECK (gwp_set IN ('AR6','AR5','AR4')),
            substance       VARCHAR(40)  NOT NULL,
            gwp100          NUMERIC(10,3) NOT NULL,
            source_citation TEXT         NOT NULL,
            valid_from      DATE         NOT NULL,
            valid_to        DATE,
            UNIQUE (gwp_set, substance)
        );
        """
    )
    # AR6 values — IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021)
    op.execute(
        """
        INSERT INTO ref.gwp_sets (gwp_set, substance, gwp100, source_citation, valid_from) VALUES
            ('AR6', 'CO2',      1.000,   'IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021)', '2021-08-01'),
            ('AR6', 'CH4',      27.900,  'IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021) — aggregate default', '2021-08-01'),
            ('AR6', 'N2O',      273.000, 'IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021)', '2021-08-01'),
            ('AR6', 'SF6',      25200.000, 'IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021)', '2021-08-01'),
            ('AR6', 'HFC-134a', 1530.000, 'IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021)', '2021-08-01'),
            ('AR6', 'HFC-410A', 2256.000, 'IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021) composite', '2021-08-01'),
            ('AR6', 'HFC-32',   771.000,  'IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 (2021)', '2021-08-01');
        """
    )
    # AR5 values — IPCC AR5 WG1 Ch.8 Table 8.7 (no climate-carbon feedback, per EU ETS 2023/2122)
    op.execute(
        """
        INSERT INTO ref.gwp_sets (gwp_set, substance, gwp100, source_citation, valid_from) VALUES
            ('AR5', 'CO2',      1.000,   'IPCC AR5 WG1 Ch.8 Table 8.7 (2014) — no climate-carbon feedback', '2014-09-01'),
            ('AR5', 'CH4',      28.000,  'IPCC AR5 WG1 Ch.8 Table 8.7 (2014) — no feedback; EU ETS 2023/2122', '2014-09-01'),
            ('AR5', 'N2O',      265.000, 'IPCC AR5 WG1 Ch.8 Table 8.7 (2014)', '2014-09-01'),
            ('AR5', 'SF6',      23500.000, 'IPCC AR5 WG1 Ch.8 Table 8.7 (2014)', '2014-09-01'),
            ('AR5', 'HFC-134a', 1300.000, 'IPCC AR5 WG1 Ch.8 Table 8.7 (2014)', '2014-09-01'),
            ('AR5', 'HFC-410A', 2088.000, 'IPCC AR5 WG1 Ch.8 Table 8.7 (2014) composite', '2014-09-01'),
            ('AR5', 'HFC-32',   677.000,  'IPCC AR5 WG1 Ch.8 Table 8.7 (2014)', '2014-09-01');
        """
    )

    # -- ref.factor_catalog (empty table; seeded in M2) ----------------------
    op.execute(
        """
        CREATE TABLE ref.factor_catalog (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL REFERENCES ref.tenants(id),
            factor_id           VARCHAR(80)  NOT NULL,
            version             VARCHAR(40)  NOT NULL,
            substance           VARCHAR(100) NOT NULL,
            scope               SMALLINT     NOT NULL CHECK (scope BETWEEN 1 AND 3),
            category            VARCHAR(40)  NOT NULL,
            source              VARCHAR(40)  NOT NULL
                                CHECK (source IN ('DEFRA','ISPRA','IEA','ecoinvent',
                                                  'EXIOBASE','CDP','IPCC','AIB','EPD',
                                                  'GHGProtocol')),
            value               NUMERIC(20,8),
            is_licence_only     BOOLEAN      NOT NULL DEFAULT FALSE,
            is_tbc              BOOLEAN      NOT NULL DEFAULT FALSE,
            biogenic_co2_kg_per_unit NUMERIC(20,8),
            unit                VARCHAR(40)  NOT NULL,
            gwp_set             VARCHAR(10)  NOT NULL CHECK (gwp_set IN ('AR6','AR5','n/a')),
            vintage             VARCHAR(40),
            valid_from          DATE         NOT NULL,
            valid_to            DATE,
            applicability_note  TEXT,
            pdf_source_uri      TEXT,
            published_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
            published_by        VARCHAR(120) NOT NULL,
            is_published        BOOLEAN      NOT NULL DEFAULT FALSE,
            UNIQUE (tenant_id, factor_id, version, gwp_set),
            CONSTRAINT chk_factor_source_nonblank CHECK (length(trim(source)) > 0)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX ix_factor_catalog_lookup
            ON ref.factor_catalog(tenant_id, factor_id, gwp_set, valid_from DESC);
        """
    )
    # Immutability post-publish (MG-02)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.deny_factor_mutation() RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.is_published THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'P0001',
                    MESSAGE = format('Factor %s/%s is published and immutable',
                                     OLD.factor_id, OLD.version);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_factor_immutable
        BEFORE UPDATE OR DELETE ON ref.factor_catalog
        FOR EACH ROW EXECUTE FUNCTION ops.deny_factor_mutation();
        """
    )

    # -- ref.go_certificate_evidence -----------------------------------------
    op.execute(
        """
        CREATE TABLE ref.go_certificate_evidence (
            id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                  UUID         NOT NULL REFERENCES ref.tenants(id),
            go_id                      VARCHAR(80)  NOT NULL,
            site_id                    UUID         NOT NULL REFERENCES ref.sites(id),
            anno                       INT          NOT NULL,
            volume_mwh                 NUMERIC(20,6) NOT NULL CHECK (volume_mwh >= 0),
            vintage_year               INT          NOT NULL,
            cancellation_date          DATE         NOT NULL,
            beneficiary_legal_entity   VARCHAR(200) NOT NULL,
            country_of_issuance        VARCHAR(40)  NOT NULL,
            technology                 VARCHAR(40)  NOT NULL,
            qc1_conveyed_claim_passed  BOOLEAN      NOT NULL,
            qc2_unique_passed          BOOLEAN      NOT NULL,
            qc3_redeemed_passed        BOOLEAN      NOT NULL,
            qc4_vintage_passed         BOOLEAN      NOT NULL,
            qc5_geographic_passed      BOOLEAN      NOT NULL,
            qc6_scope_passed           BOOLEAN      NOT NULL,
            qc7_exclusivity_passed     BOOLEAN      NOT NULL,
            qc8_residual_mix_disclosed BOOLEAN      NOT NULL,
            pdf_evidence_uri           TEXT         NOT NULL,
            validated_by               VARCHAR(120) NOT NULL,
            validated_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, go_id)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX ix_go_evidence_site_year
            ON ref.go_certificate_evidence(tenant_id, site_id, anno);

        CREATE VIEW ref.v_go_certificate_qc_pass AS
        SELECT id, tenant_id, go_id, site_id, anno, volume_mwh,
               (qc1_conveyed_claim_passed AND qc2_unique_passed AND
                qc3_redeemed_passed AND qc4_vintage_passed AND
                qc5_geographic_passed AND qc6_scope_passed AND
                qc7_exclusivity_passed AND qc8_residual_mix_disclosed) AS all_qc_passed
        FROM ref.go_certificate_evidence;
        """
    )

    # -- raw.ingestion_batches ------------------------------------------------
    op.execute(
        """
        CREATE TABLE raw.ingestion_batches (
            batch_id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                  UUID         NOT NULL REFERENCES ref.tenants(id),
            correlation_id             UUID         NOT NULL,
            run_started_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
            run_completed_at           TIMESTAMPTZ,
            etl_version                VARCHAR(40)  NOT NULL,
            gwp_set                    VARCHAR(10)  NOT NULL CHECK (gwp_set IN ('AR6','AR5')),
            triggered_by               VARCHAR(120) NOT NULL,
            source_file_scope1_sha256  CHAR(64),
            source_file_scope2_sha256  CHAR(64),
            source_file_scope3_sha256  CHAR(64),
            notes                      TEXT
        );
        CREATE INDEX ix_ingestion_batches_correlation ON raw.ingestion_batches(correlation_id);
        CREATE INDEX ix_ingestion_batches_started ON raw.ingestion_batches(run_started_at DESC);
        """
    )

    # -- raw.scope1_ingestions -----------------------------------------------
    op.execute(
        """
        CREATE TABLE raw.scope1_ingestions (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID         NOT NULL REFERENCES ref.tenants(id),
            batch_id             UUID         NOT NULL REFERENCES raw.ingestion_batches(batch_id),
            scope                SMALLINT     NOT NULL CHECK (scope = 1),
            anno                 INT          NOT NULL CHECK (anno BETWEEN 2020 AND 2099),
            codice_sito          VARCHAR(40)  NOT NULL,
            categoria_s1         VARCHAR(40)  NOT NULL,
            combustibile         VARCHAR(40)  NOT NULL,
            quantita             NUMERIC(20,6) NOT NULL CHECK (quantita >= 0),
            unita                VARCHAR(20)  NOT NULL,
            fonte_dato           VARCHAR(120) NOT NULL,
            qualita_dato         VARCHAR(4)   NOT NULL,
            stato_dato           VARCHAR(20)  NOT NULL,
            note                 TEXT,
            provenance           VARCHAR(60),
            provenance_rationale TEXT,
            idempotency_key      VARCHAR(120) NOT NULL,
            ingested_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            ingested_by          VARCHAR(120) NOT NULL,
            UNIQUE (tenant_id, batch_id, idempotency_key)
        );
        CREATE INDEX ix_raw_s1_keys
            ON raw.scope1_ingestions(tenant_id, anno, codice_sito, combustibile);
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_raw_s1_deny_mutation
        BEFORE UPDATE OR DELETE ON raw.scope1_ingestions
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )

    # -- raw.scope2_ingestions -----------------------------------------------
    op.execute(
        """
        CREATE TABLE raw.scope2_ingestions (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID         NOT NULL REFERENCES ref.tenants(id),
            batch_id             UUID         NOT NULL REFERENCES raw.ingestion_batches(batch_id),
            scope                SMALLINT     NOT NULL CHECK (scope = 2),
            anno                 INT          NOT NULL CHECK (anno BETWEEN 2020 AND 2099),
            codice_sito          VARCHAR(40)  NOT NULL,
            voce_s2              VARCHAR(40)  NOT NULL
                                 CHECK (voce_s2 IN ('EE_Acquistata_GO','EE_Acquistata_Grid')),
            quantita             NUMERIC(20,6) NOT NULL CHECK (quantita >= 0),
            unita                VARCHAR(20)  NOT NULL CHECK (unita = 'kWh'),
            strumento_mb         VARCHAR(40),
            fonte_dato           VARCHAR(120) NOT NULL,
            qualita_dato         VARCHAR(4)   NOT NULL,
            stato_dato           VARCHAR(20)  NOT NULL,
            note                 TEXT,
            provenance           VARCHAR(60),
            provenance_rationale TEXT,
            idempotency_key      VARCHAR(120) NOT NULL,
            ingested_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            ingested_by          VARCHAR(120) NOT NULL,
            UNIQUE (tenant_id, batch_id, idempotency_key)
        );
        CREATE INDEX ix_raw_s2_keys
            ON raw.scope2_ingestions(tenant_id, anno, codice_sito, voce_s2);
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_raw_s2_deny_mutation
        BEFORE UPDATE OR DELETE ON raw.scope2_ingestions
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )

    # -- raw.scope3_ingestions -----------------------------------------------
    op.execute(
        """
        CREATE TABLE raw.scope3_ingestions (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID         NOT NULL REFERENCES ref.tenants(id),
            batch_id             UUID         NOT NULL REFERENCES raw.ingestion_batches(batch_id),
            scope                SMALLINT     NOT NULL CHECK (scope = 3),
            anno                 INT          NOT NULL CHECK (anno BETWEEN 2020 AND 2099),
            categoria_s3         INT          NOT NULL CHECK (categoria_s3 BETWEEN 1 AND 15),
            sottocategoria       VARCHAR(200) NOT NULL,
            metodo               VARCHAR(40)  NOT NULL,
            combustibile         VARCHAR(40),
            quantita             NUMERIC(20,6) NOT NULL CHECK (quantita >= 0),
            unita                VARCHAR(20)  NOT NULL,
            fonte_dato           VARCHAR(120) NOT NULL,
            qualita_dato         VARCHAR(4)   NOT NULL,
            stato_dato           VARCHAR(20)  NOT NULL,
            note                 TEXT,
            metadata_defaulted   BOOLEAN      NOT NULL DEFAULT FALSE,
            defaulting_rule_id   VARCHAR(20),
            idempotency_key      VARCHAR(160) NOT NULL,
            ingested_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            ingested_by          VARCHAR(120) NOT NULL,
            UNIQUE (tenant_id, batch_id, idempotency_key)
        );
        CREATE INDEX ix_raw_s3_keys
            ON raw.scope3_ingestions(tenant_id, anno, categoria_s3, sottocategoria);
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_raw_s3_deny_mutation
        BEFORE UPDATE OR DELETE ON raw.scope3_ingestions
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )


def downgrade() -> None:
    """Reverse M0 — drop all objects created in upgrade() in dependency order."""
    # Raw tables
    op.execute("DROP TABLE IF EXISTS raw.scope3_ingestions CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw.scope2_ingestions CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw.scope1_ingestions CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw.ingestion_batches CASCADE;")
    # Reference tables
    op.execute("DROP VIEW IF EXISTS ref.v_go_certificate_qc_pass CASCADE;")
    op.execute("DROP TABLE IF EXISTS ref.go_certificate_evidence CASCADE;")
    op.execute("DROP TABLE IF EXISTS ref.factor_catalog CASCADE;")
    op.execute("DROP TABLE IF EXISTS ref.gwp_sets CASCADE;")
    op.execute("DROP TABLE IF EXISTS ref.users CASCADE;")
    op.execute("DROP TABLE IF EXISTS ref.roles CASCADE;")
    op.execute("DROP TABLE IF EXISTS ref.sites CASCADE;")
    op.execute("DROP TABLE IF EXISTS ref.tenants CASCADE;")
    # Functions
    op.execute("DROP FUNCTION IF EXISTS ops.deny_factor_mutation() CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS ops.deny_mutation() CASCADE;")
    # Extensions
    # pg_stat_statements creates two views in the public schema
    # (pg_stat_statements and pg_stat_statements_info on PG14+) that appear in
    # information_schema.tables and would cause the downgrade round-trip test to
    # report non-zero leftover user tables.  Drop the extension with CASCADE to
    # remove those views before dropping the named schemas below.
    # pgcrypto is left in place: it only creates functions (not tables/views) so
    # it does not contribute to the leftover-table count, and dropping it is
    # unnecessary for the round-trip test to pass.
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements CASCADE;")
    # Schemas (auth is created by a later migration; drop it here so the schema
    # does not linger after a full downgrade-to-base on a fresh database).
    op.execute("DROP SCHEMA IF EXISTS auth CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS ops CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS mv CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS calc CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS ref CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS raw CASCADE;")
