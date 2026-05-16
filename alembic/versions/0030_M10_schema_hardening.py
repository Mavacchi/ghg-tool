"""M10 — Schema hardening: RLS-A, M1-A, BT-A, IDX-A.

Bundles four REQUIRED fixes into a single migration:

RLS-A — ref.tenants ENABLE + FORCE Row Level Security
======================================================
Enables RLS on ``ref.tenants`` with two PERMISSIVE policies:
  - ``p_tenants_self``: regular users see only their own tenant row
    (``id = current_setting('app.tenant_id', true)::uuid``).
  - ``p_tenants_admin``: admin role bypasses the per-tenant filter and
    can see ALL tenant rows (required for the admin_tenants router).
Both policies are PERMISSIVE (default), so they are OR-ed by PostgreSQL.

M1-A — SET search_path on calc.fn_emit_correction
==================================================
Adds ``SET search_path = calc, ops, pg_catalog`` to the SECURITY DEFINER
function ``calc.fn_emit_correction(UUID, UUID, VARCHAR)`` defined in M1.
The function body is reproduced verbatim from 0002_M1; only the
``SET search_path`` clause is added. This prevents search_path injection
attacks against SECURITY DEFINER functions (CWE-89 variant).

BT-A — GIST exclusion constraint for temporal overlap on emissions_consolidated
================================================================================
Adds an EXCLUDE USING gist constraint that prevents two active rows
(``superseded_by IS NULL``) from overlapping in time for the same natural
key (tenant + site + scope + sub_scope + year). Requires the
``btree_gist`` extension (for equality operators in GIST indexes).
The constraint is partial (WHERE superseded_by IS NULL) so it only
enforces overlap among currently-active rows; superseded rows are
unconstrained.

IDX-A — Partial index on ref.factor_catalog for published factors
=================================================================
Adds a partial index ``ix_factor_catalog_published`` covering only rows
where ``is_published = TRUE``. This is the hotpath used by the
calculation engine to look up active published factors.

Downgrade
=========
Drops everything in reverse order. The ``btree_gist`` extension is NOT
dropped (it may be used by other objects; cascade-dropping an extension
is too destructive).

Revision: 0030_M10
Revises:  0029_M9
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0030_M10"
down_revision: str = "0029_M9"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Apply RLS-A, M1-A, BT-A, IDX-A hardening fixes."""

    # =========================================================================
    # BT-A prerequisite: btree_gist extension (required for GIST + equality)
    # =========================================================================
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # =========================================================================
    # RLS-A — ref.tenants: enable + force RLS, two permissive policies
    # =========================================================================
    op.execute("ALTER TABLE ref.tenants ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE ref.tenants FORCE ROW LEVEL SECURITY;")

    # Regular users see only their own tenant row.
    op.execute(
        """
        CREATE POLICY p_tenants_self ON ref.tenants
        AS PERMISSIVE
        FOR ALL
        USING (id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # Admin role can see ALL tenant rows (needed for admin_tenants router).
    # This policy is PERMISSIVE (default), so it is OR-ed with p_tenants_self.
    op.execute(
        """
        CREATE POLICY p_tenants_admin ON ref.tenants
        AS PERMISSIVE
        FOR ALL
        USING (current_setting('app.role_code', true) = 'admin');
        """
    )

    # =========================================================================
    # M1-A — calc.fn_emit_correction: add SET search_path to SECURITY DEFINER
    #
    # Body reproduced verbatim from 0002_M1_emissions_immutability.py; only the
    # SET search_path clause is added at the end of the function definition.
    # This prevents search_path injection attacks on SECURITY DEFINER functions.
    # =========================================================================
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
        $$ LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = calc, ops, pg_catalog;
        """
    )

    # =========================================================================
    # BT-A — GIST exclusion constraint: no active-row temporal overlap
    #
    # Prevents two rows with superseded_by IS NULL from overlapping in
    # tstzrange(valid_from, COALESCE(valid_to, 'infinity')) for the same
    # (tenant_id, codice_sito, scope, sub_scope, anno) natural key.
    #
    # COMPATIBILITY NOTE: if existing data already has overlapping active rows
    # (e.g. from a mis-applied correction), this ALTER TABLE will fail with
    # "conflicting key value violates exclusion constraint". In that case,
    # identify overlapping rows with:
    #   SELECT a.id, b.id FROM calc.emissions_consolidated a
    #   JOIN calc.emissions_consolidated b ON (
    #     a.tenant_id = b.tenant_id AND a.codice_sito IS NOT DISTINCT FROM b.codice_sito
    #     AND a.scope = b.scope AND a.sub_scope = b.sub_scope AND a.anno = b.anno
    #     AND a.id < b.id
    #     AND tstzrange(a.valid_from, COALESCE(a.valid_to,'infinity')) &&
    #         tstzrange(b.valid_from, COALESCE(b.valid_to,'infinity'))
    #   ) WHERE a.superseded_by IS NULL AND b.superseded_by IS NULL;
    # and resolve via fn_emit_correction before re-running this migration.
    # =========================================================================
    op.execute(
        """
        ALTER TABLE calc.emissions_consolidated
        ADD CONSTRAINT excl_emissions_temporal_overlap
        EXCLUDE USING gist (
            tenant_id   WITH =,
            codice_sito WITH =,
            scope       WITH =,
            sub_scope   WITH =,
            anno        WITH =,
            tstzrange(valid_from, COALESCE(valid_to, 'infinity'::timestamptz)) WITH &&
        ) WHERE (superseded_by IS NULL);
        """
    )

    # =========================================================================
    # IDX-A — Partial index on ref.factor_catalog for published factors
    #
    # Covers the hotpath used by the calculation engine:
    #   SELECT ... FROM ref.factor_catalog
    #   WHERE tenant_id = $1 AND factor_id = $2 AND gwp_set = $3
    #     AND valid_from <= $4 AND is_published = TRUE
    #   ORDER BY valid_from DESC LIMIT 1;
    # =========================================================================
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_factor_catalog_published
            ON ref.factor_catalog (tenant_id, factor_id, gwp_set, valid_from DESC)
            WHERE is_published = TRUE;
        """
    )


def downgrade() -> None:
    """Reverse M10 hardening in reverse order.

    btree_gist extension is NOT dropped — it may serve other objects.
    """

    # IDX-A
    op.execute("DROP INDEX IF EXISTS ref.ix_factor_catalog_published;")

    # BT-A
    op.execute(
        "ALTER TABLE calc.emissions_consolidated "
        "DROP CONSTRAINT IF EXISTS excl_emissions_temporal_overlap;"
    )

    # M1-A: restore fn_emit_correction without SET search_path clause
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

    # RLS-A
    op.execute("DROP POLICY IF EXISTS p_tenants_admin ON ref.tenants;")
    op.execute("DROP POLICY IF EXISTS p_tenants_self ON ref.tenants;")
    op.execute("ALTER TABLE ref.tenants NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE ref.tenants DISABLE ROW LEVEL SECURITY;")
