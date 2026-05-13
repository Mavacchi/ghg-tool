"""M1 — Emissions consolidated table with full immutability enforcement.

Creates calc.emissions_consolidated with:
  - Bitemporal valid_from / valid_to / superseded_by
  - ADR-007: co2_biogenic_tonne + co2_fossil_tonne columns
  - regulatory_stream column for AR5 dual-track (FR-34)
  - deny_emissions_mutation trigger (FR-20, NFR-14, NFR-21, CG-03)
  - fn_emit_correction SECURITY DEFINER procedure (FR-21)
  - calc.audit_log table

Revision: 0002_M1
Revises: 0001_M0
"""

from __future__ import annotations

from alembic import op

revision: str = "0002_M1"
down_revision: str = "0001_M0"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create emissions_consolidated, immutability trigger, correction proc, audit_log."""

    # -- calc.emissions_consolidated ------------------------------------------
    op.execute(
        """
        CREATE TABLE calc.emissions_consolidated (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID         NOT NULL REFERENCES ref.tenants(id),
            correlation_id    UUID         NOT NULL,
            raw_row_id        UUID         NOT NULL,
            raw_scope         SMALLINT     NOT NULL CHECK (raw_scope IN (1,2,3)),
            scope             SMALLINT     NOT NULL CHECK (scope IN (1,2,3)),
            sub_scope         VARCHAR(40)  NOT NULL,
            codice_sito       VARCHAR(40),
            anno              INT          NOT NULL CHECK (anno BETWEEN 2020 AND 2099),
            tco2e             NUMERIC(18,6) NOT NULL CHECK (tco2e >= 0),
            co2_tonne         NUMERIC(18,6),
            ch4_tco2e         NUMERIC(18,6),
            n2o_tco2e         NUMERIC(18,6),
            -- ADR-007: biogenic CO2 columns — disclosed separately, NEVER netted
            co2_biogenic_tonne NUMERIC(18,6),
            co2_fossil_tonne   NUMERIC(18,6),
            factor_id         UUID         NOT NULL REFERENCES ref.factor_catalog(id),
            factor_version    VARCHAR(40)  NOT NULL,
            factor_source     VARCHAR(40)  NOT NULL,
            gwp_set           VARCHAR(10)  NOT NULL CHECK (gwp_set IN ('AR6','AR5')),
            methodology       VARCHAR(40)  NOT NULL,
            regulatory_stream VARCHAR(40)  NOT NULL DEFAULT 'CSRD_ESRS_E1',
            calc_timestamp    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            created_by        VARCHAR(120) NOT NULL,
            valid_from        TIMESTAMPTZ  NOT NULL DEFAULT now(),
            valid_to          TIMESTAMPTZ,
            superseded_by     UUID REFERENCES calc.emissions_consolidated(id),
            reason_code       VARCHAR(40),
            disclosure_notes  TEXT,
            CONSTRAINT chk_metadata_nonnull
                CHECK (factor_source IS NOT NULL AND
                       factor_version IS NOT NULL AND
                       gwp_set IS NOT NULL AND
                       methodology IS NOT NULL),
            CONSTRAINT chk_active_consistency
                CHECK ((valid_to IS NULL AND superseded_by IS NULL) OR
                       (valid_to IS NOT NULL AND superseded_by IS NOT NULL)),
            CONSTRAINT chk_regulatory_stream
                CHECK (regulatory_stream IN ('CSRD_ESRS_E1','EU_ETS_PHASE_IV'))
        );
        """
    )

    # Bitemporal partial unique index — at most one active row per natural key
    op.execute(
        """
        CREATE UNIQUE INDEX ux_emissions_active_natural_key
            ON calc.emissions_consolidated (
                tenant_id, scope, sub_scope,
                COALESCE(codice_sito, ''),
                anno, regulatory_stream, gwp_set
            )
            WHERE valid_to IS NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX ix_emissions_scope_year_site
            ON calc.emissions_consolidated(tenant_id, scope, anno, codice_sito);
        CREATE INDEX ix_emissions_correlation
            ON calc.emissions_consolidated(correlation_id);
        CREATE INDEX ix_emissions_superseded
            ON calc.emissions_consolidated(superseded_by)
            WHERE superseded_by IS NOT NULL;
        """
    )

    # -- Immutability trigger -------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.deny_emissions_mutation() RETURNS TRIGGER AS $$
        DECLARE
            in_correction TEXT;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'P0001',
                    MESSAGE = 'DELETE forbidden on calc.emissions_consolidated';
            END IF;
            -- Allow UPDATE only inside correction stored procedure
            in_correction := current_setting('app.correction_in_progress', true);
            IF in_correction IS DISTINCT FROM 'true' THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'P0001',
                    MESSAGE = 'UPDATE forbidden on calc.emissions_consolidated '
                              'outside the correction stored procedure';
            END IF;
            -- Even inside correction, only valid_to / superseded_by / reason_code may change
            IF NEW.id              <> OLD.id              OR
               NEW.tco2e           <> OLD.tco2e           OR
               NEW.factor_id       <> OLD.factor_id       OR
               NEW.factor_version  <> OLD.factor_version  OR
               NEW.gwp_set         <> OLD.gwp_set         OR
               NEW.methodology     <> OLD.methodology     OR
               NEW.scope           <> OLD.scope           OR
               NEW.anno            <> OLD.anno            OR
               NEW.codice_sito IS DISTINCT FROM OLD.codice_sito THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'P0001',
                    MESSAGE = 'Correction may only set valid_to, superseded_by, reason_code';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_emissions_deny_mutation
        BEFORE UPDATE OR DELETE ON calc.emissions_consolidated
        FOR EACH ROW EXECUTE FUNCTION ops.deny_emissions_mutation();
        """
    )

    # -- fn_emit_correction SECURITY DEFINER (FR-21) -------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION calc.fn_emit_correction(
            p_predecessor_id UUID,
            p_new_id         UUID,
            p_reason_code    VARCHAR
        ) RETURNS VOID AS $$
        BEGIN
            IF p_reason_code NOT IN (
                'DATA_ERROR','FACTOR_UPDATE','BOUNDARY_CHANGE',
                'METHODOLOGY_REVISION','RESTATEMENT_>5PCT'
            ) THEN
                RAISE EXCEPTION 'Invalid reason_code: %', p_reason_code;
            END IF;
            PERFORM set_config('app.correction_in_progress', 'true', true);
            UPDATE calc.emissions_consolidated
               SET valid_to      = now(),
                   superseded_by = p_new_id,
                   reason_code   = p_reason_code
             WHERE id = p_predecessor_id
               AND valid_to IS NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Predecessor row not found or already superseded: %',
                    p_predecessor_id;
            END IF;
            PERFORM set_config('app.correction_in_progress', 'false', true);
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
        """
    )

    # -- calc.audit_log -------------------------------------------------------
    op.execute(
        """
        CREATE TABLE calc.audit_log (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL REFERENCES ref.tenants(id),
            correlation_id  UUID         NOT NULL,
            occurred_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            user_id         UUID REFERENCES ref.users(id),
            user_role       VARCHAR(40)  NOT NULL,
            action          VARCHAR(60)  NOT NULL,
            resource        VARCHAR(60),
            resource_id     UUID,
            request_method  VARCHAR(10),
            request_path    TEXT,
            status_code     SMALLINT,
            ip_address      INET,
            user_agent      TEXT,
            before_state    JSONB,
            after_state     JSONB,
            extra           JSONB
        );
        CREATE INDEX ix_audit_log_user_time
            ON calc.audit_log(user_id, occurred_at DESC);
        CREATE INDEX ix_audit_log_action
            ON calc.audit_log(action, occurred_at DESC);
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_deny_mutation
        BEFORE UPDATE OR DELETE ON calc.audit_log
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )


def downgrade() -> None:
    """Reverse M1."""
    op.execute("DROP TABLE IF EXISTS calc.audit_log CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS calc.fn_emit_correction(UUID,UUID,VARCHAR) CASCADE;")
    op.execute("DROP TABLE IF EXISTS calc.emissions_consolidated CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS ops.deny_emissions_mutation() CASCADE;")
