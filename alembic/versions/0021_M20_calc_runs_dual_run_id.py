"""M20 -- Add dual_run_id self-referential FK to ops.calc_runs.

Backs sustainability-expert-agent's overturned Q1 decision (option A) for
dual-track CSRD/ETS traceability per Reg. UE 2018/2067 Art. 6.

Changes:
1. ADD COLUMN ops.calc_runs.dual_run_id UUID NULL
   Self-referential FK to ops.calc_runs.id ON DELETE SET NULL.
   NULL is legal: single-track (CSRD-only) runs for tenants with no EU ETS
   installation (methodology §11).

2. CREATE INDEX ix_calc_runs_dual_run_id ON ops.calc_runs (dual_run_id)
   For verifier join performance (Reg. 2018/2067 Art. 6 / ISAE 3000 §A99).

3. ADD CONSTRAINT ck_calc_runs_no_self_dual
   CHECK (dual_run_id IS NULL OR dual_run_id <> id)
   Prevents a row from referencing itself.

4. CREATE FUNCTION ops.enforce_dual_run_reciprocity() + TRIGGER
   DEFERRABLE INITIALLY DEFERRED so that both rows of a dual-track pair
   can be INSERTed inside a single transaction using pre-generated UUIDs
   before the constraint fires at COMMIT time.

   Enforces three invariants when dual_run_id IS NOT NULL:
   a. The referenced row must share (tenant_id, anno) with this row.
   b. The referenced row must have a DIFFERENT regulatory_stream.
   c. The relation must be reciprocal: the referenced row's dual_run_id
      must equal this row's id.

   This trigger is on ops.calc_runs ONLY. It does NOT touch
   calc.emissions_consolidated or any other ledger table. The existing
   ops.deny_emissions_mutation() guard on calc.emissions_consolidated
   is not affected.

Revision: 0021_M20
Revises:  0020_M19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# ---------------------------------------------------------------------------
revision: str = "0021_M20"
down_revision: str = "0020_M19"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "ops"
_TABLE = "calc_runs"
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Add dual_run_id column, index, CHECK constraint, and reciprocity trigger."""

    # -------------------------------------------------------------------------
    # 1. Column: dual_run_id UUID NULL with self-referential FK
    # -------------------------------------------------------------------------
    op.add_column(
        _TABLE,
        sa.Column(
            "dual_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "ops.calc_runs.id",
                ondelete="SET NULL",
                name="fk_calc_runs_dual_run_id",
            ),
            nullable=True,
        ),
        schema=_SCHEMA,
    )

    # -------------------------------------------------------------------------
    # 2. Index for verifier join performance
    # -------------------------------------------------------------------------
    op.create_index(
        "ix_calc_runs_dual_run_id",
        _TABLE,
        ["dual_run_id"],
        schema=_SCHEMA,
    )

    # -------------------------------------------------------------------------
    # 3. CHECK constraint: no self-reference
    # -------------------------------------------------------------------------
    op.create_check_constraint(
        "ck_calc_runs_no_self_dual",
        _TABLE,
        "dual_run_id IS NULL OR dual_run_id <> id",
        schema=_SCHEMA,
    )

    # -------------------------------------------------------------------------
    # 4. Reciprocity trigger
    #
    # Enforces (when dual_run_id IS NOT NULL):
    #   a. Paired row shares (tenant_id, anno)
    #   b. Paired row has a DIFFERENT regulatory_stream
    #   c. Paired row's dual_run_id = this row's id  (reciprocity)
    #
    # DEFERRABLE INITIALLY DEFERRED: fires at COMMIT, not at statement end.
    # This allows the two-row insert pattern (pre-generated UUIDs) within a
    # single transaction without a chicken-and-egg FK violation.
    #
    # The trigger is placed on ops.calc_runs ONLY.  It does not interact with
    # ops.deny_emissions_mutation(), which guards calc.emissions_consolidated.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.enforce_dual_run_reciprocity()
        RETURNS trigger AS $$
        DECLARE
            paired RECORD;
        BEGIN
            -- Nothing to check when dual_run_id is NULL (single-track run).
            IF NEW.dual_run_id IS NULL THEN
                RETURN NEW;
            END IF;

            -- Fetch the paired row.
            SELECT tenant_id, anno, regulatory_stream, dual_run_id
              INTO paired
              FROM ops.calc_runs
             WHERE id = NEW.dual_run_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'dual_run_id % does not reference an existing ops.calc_runs row',
                    NEW.dual_run_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            -- (a) Paired row must share (tenant_id, anno).
            IF paired.tenant_id IS DISTINCT FROM NEW.tenant_id
               OR paired.anno IS DISTINCT FROM NEW.anno
            THEN
                RAISE EXCEPTION
                    'dual_run_id integrity: paired rows must share (tenant_id, anno). '
                    'This row: (%, %); paired row: (%, %)',
                    NEW.tenant_id, NEW.anno, paired.tenant_id, paired.anno
                    USING ERRCODE = 'check_violation';
            END IF;

            -- (b) Paired row must have a DIFFERENT regulatory_stream.
            IF paired.regulatory_stream = NEW.regulatory_stream THEN
                RAISE EXCEPTION
                    'dual_run_id integrity: paired rows must have different '
                    'regulatory_stream values. Both rows have: %',
                    NEW.regulatory_stream
                    USING ERRCODE = 'check_violation';
            END IF;

            -- (c) Reciprocity: paired row's dual_run_id must equal this row's id.
            -- NULL is allowed during the deferred window (second INSERT not yet
            -- committed); once the trigger fires at COMMIT both rows must point
            -- to each other.
            IF paired.dual_run_id IS NOT NULL
               AND paired.dual_run_id IS DISTINCT FROM NEW.id
            THEN
                RAISE EXCEPTION
                    'dual_run_id integrity: reciprocity violation. '
                    'Row % has dual_run_id = %, expected % or NULL',
                    NEW.dual_run_id, paired.dual_run_id, NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # NOTE: PostgreSQL CONSTRAINT TRIGGER does NOT support `OF column_name`
    # (only AFTER {INSERT|UPDATE|DELETE} without column lists). The original
    # `AFTER INSERT OR UPDATE OF dual_run_id` syntax raised a parse error on
    # real Postgres. Append-only on ops.calc_runs is enforced by the
    # deny_calc_runs_mutation trigger added in 0023_M22, so we only need
    # AFTER INSERT here (the only event allowed to add a dual_run_id value).
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_calc_runs_dual_run_reciprocity
        AFTER INSERT ON ops.calc_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION ops.enforce_dual_run_reciprocity();
        """
    )


def downgrade() -> None:
    """Remove the reciprocity trigger, function, check, index, FK, and column."""

    # 1. Drop trigger (must drop before function)
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_calc_runs_dual_run_reciprocity
            ON ops.calc_runs;
        """
    )

    # 2. Drop function
    op.execute(
        "DROP FUNCTION IF EXISTS ops.enforce_dual_run_reciprocity();"
    )

    # 3. Drop CHECK constraint
    op.drop_constraint(
        "ck_calc_runs_no_self_dual",
        _TABLE,
        schema=_SCHEMA,
        type_="check",
    )

    # 4. Drop index
    op.drop_index(
        "ix_calc_runs_dual_run_id",
        table_name=_TABLE,
        schema=_SCHEMA,
    )

    # 5. Drop FK constraint (implicit via drop_column, but explicit is safer)
    op.drop_constraint(
        "fk_calc_runs_dual_run_id",
        _TABLE,
        schema=_SCHEMA,
        type_="foreignkey",
    )

    # 6. Drop column
    op.drop_column(_TABLE, "dual_run_id", schema=_SCHEMA)
