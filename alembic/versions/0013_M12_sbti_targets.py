"""M12 -- Create ref.sbti_targets (ESRS E1-4 SBTi-aligned reduction targets).

Adds the ``ref.sbti_targets`` table that backs the SbtiTarget domain entity.

Immutability semantics:
  - All columns are immutable EXCEPT ``is_active``.
  - ``is_active`` may only transition True -> False (deactivation).
  - The trigger ``trg_sbti_target_immutability`` enforces this at the DB layer.
  - Partial UNIQUE index ensures at most one active target per
    (tenant_id, scope_coverage) pair.

Revision: 0013_M12
Revises: 0012_M13 (report_snapshots -- highest revision in chain)
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0013_M12"
down_revision: str = "0012_M13"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "ref"
_TABLE = "sbti_targets"
_TRIGGER_FN = "trg_fn_sbti_target_immutability"
_TRIGGER = "trg_sbti_target_immutability"
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Create ref.sbti_targets, indexes, immutability trigger, and RLS."""

    op.execute(
        f"""
        CREATE TABLE {_SCHEMA}.{_TABLE} (
            target_id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL REFERENCES ref.tenants(id),
            name                    VARCHAR(200) NOT NULL,
            scope_coverage          VARCHAR(40) NOT NULL
                CONSTRAINT chk_sbti_targets_scope_coverage
                CHECK (scope_coverage IN (
                    'S1','S2_LB','S2_MB','S3',
                    'S1+S2_LB','S1+S2_MB','S1+S2_MB+S3'
                )),
            baseline_year           SMALLINT    NOT NULL,
            baseline_tco2e          NUMERIC(18,3) NOT NULL
                CONSTRAINT chk_sbti_targets_baseline_positive
                CHECK (baseline_tco2e > 0),
            target_year             SMALLINT    NOT NULL
                CONSTRAINT chk_sbti_targets_year_order
                CHECK (target_year > baseline_year),
            target_tco2e            NUMERIC(18,3) NOT NULL
                CONSTRAINT chk_sbti_targets_target_lte_baseline
                CHECK (target_tco2e >= 0 AND target_tco2e <= baseline_tco2e),
            reduction_pct           NUMERIC(8,4)  NOT NULL,
            alignment               VARCHAR(10) NOT NULL
                CONSTRAINT chk_sbti_targets_alignment
                CHECK (alignment IN ('1.5C','WB2C','2C')),
            methodology             VARCHAR(40) NOT NULL
                CONSTRAINT chk_sbti_targets_methodology
                CHECK (methodology IN (
                    'SBTi_ACA','SDA','GEVA','SBTi_NetZero',
                    'supplier_engagement','custom'
                )),
            sbti_approval_status    VARCHAR(20) NOT NULL
                CONSTRAINT chk_sbti_targets_sbti_approval_status
                CHECK (sbti_approval_status IN (
                    'none','committed','targets_set','validated'
                )),
            sbti_validation_date    DATE,
            created_by              VARCHAR(120) NOT NULL,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            is_active               BOOLEAN      NOT NULL DEFAULT TRUE
        );
        """
    )

    # Composite index: list active targets for a tenant by target year.
    op.execute(
        f"""
        CREATE INDEX ix_sbti_targets_tenant_year_active
            ON {_SCHEMA}.{_TABLE} (tenant_id, target_year, is_active);
        """
    )

    # Partial UNIQUE: only one ACTIVE target per (tenant, scope_coverage).
    # A deactivated (is_active=false) row does NOT block a new active one.
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_sbti_targets_tenant_scope_active
            ON {_SCHEMA}.{_TABLE} (tenant_id, scope_coverage)
            WHERE is_active = true;
        """
    )

    # Immutability trigger: allow only is_active True->False; block everything else.
    # Mirrors the pattern from trg_factor_immutable (M0) and trg_fpa_deny_mutation (M11).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_SCHEMA}.{_TRIGGER_FN}()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            -- Allow only the is_active True->False deactivation transition.
            IF (
                OLD.is_active = TRUE
                AND NEW.is_active = FALSE
                AND OLD.target_id    = NEW.target_id
                AND OLD.tenant_id    = NEW.tenant_id
                AND OLD.name         = NEW.name
                AND OLD.scope_coverage = NEW.scope_coverage
                AND OLD.baseline_year  = NEW.baseline_year
                AND OLD.baseline_tco2e = NEW.baseline_tco2e
                AND OLD.target_year    = NEW.target_year
                AND OLD.target_tco2e   = NEW.target_tco2e
                AND OLD.reduction_pct  = NEW.reduction_pct
                AND OLD.alignment      = NEW.alignment
                AND OLD.methodology    = NEW.methodology
                AND OLD.sbti_approval_status = NEW.sbti_approval_status
                AND (OLD.sbti_validation_date IS NOT DISTINCT FROM NEW.sbti_validation_date)
                AND OLD.created_by   = NEW.created_by
                AND OLD.created_at   = NEW.created_at
            ) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION
                'SBTi target % is immutable; only is_active True->False is permitted',
                OLD.target_id
                USING ERRCODE = 'P0001';
        END;
        $$;
        """
    )

    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_SCHEMA}.{_TABLE}
        FOR EACH ROW
        EXECUTE FUNCTION {_SCHEMA}.{_TRIGGER_FN}();
        """
    )

    # RLS: tenant isolation -- SELECT scoped to caller's tenant.
    op.execute(f"ALTER TABLE {_SCHEMA}.{_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_SCHEMA}.{_TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY p_sbti_targets_tenant ON {_SCHEMA}.{_TABLE}
        FOR ALL
        USING (tenant_id::text = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    """Drop ref.sbti_targets and all associated objects."""
    op.execute(
        f"DROP POLICY IF EXISTS p_sbti_targets_tenant ON {_SCHEMA}.{_TABLE};"
    )
    op.execute(f"ALTER TABLE {_SCHEMA}.{_TABLE} DISABLE ROW LEVEL SECURITY;")
    op.execute(
        f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_SCHEMA}.{_TABLE};"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS {_SCHEMA}.{_TRIGGER_FN}();"
    )
    op.execute(
        f"DROP INDEX IF EXISTS {_SCHEMA}.uq_sbti_targets_tenant_scope_active;"
    )
    op.execute(
        f"DROP INDEX IF EXISTS ix_sbti_targets_tenant_year_active;"
    )
    op.execute(f"DROP TABLE IF EXISTS {_SCHEMA}.{_TABLE};")
