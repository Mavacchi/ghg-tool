"""M22 -- Enforce append-only on ops.calc_runs (compliance Q2 mandate).

Closes the gap between migration M20 and the Q2 compliance decision:

  Q2 mandates: "No UPDATE ops.calc_runs statement may exist anywhere"
  and "The RLS / trigger policy ops.deny_emissions_mutation() MUST be
  extended to ops.calc_runs denying both UPDATE and DELETE."

  But M20 defined the reciprocity trigger as:
    AFTER INSERT OR UPDATE OF dual_run_id ON ops.calc_runs
  -- explicitly permitting UPDATE.

Changes applied here:

1. DROP the M20 reciprocity trigger and re-create it as AFTER INSERT ONLY.
   The OR UPDATE OF dual_run_id clause is removed.  Reciprocity is still
   enforced because pre-generated UUIDs make both rows correct at INSERT
   time, and the trigger is DEFERRABLE INITIALLY DEFERRED so it fires at
   COMMIT, not row-by-row.

2. CREATE trigger ops.deny_calc_runs_mutation (via function
   ops.deny_calc_runs_mutation_fn) attached BEFORE UPDATE OR DELETE ON
   ops.calc_runs FOR EACH ROW.  Raises EXCEPTION with the canonical
   append-only message to block any mutation attempt at the DB layer,
   independent of application code.

Normative basis:
  - Q2 Decision (compliance-agent) — verbatim mandate in WIP_QUESTIONS.md.
  - methodology.md §7 (Audit Trail Integrity): ops.calc_runs participates
    in the append-only family enforced by ops.deny_emissions_mutation().
  - GDPR Art. 5(1)(d) + Art. 30: every persisted row state must be final.
  - Reg. UE 2018/2067 Art. 6: INSERT-only pair is self-evident evidence;
    an INSERT-then-UPDATE pair requires log forensics to corroborate.
  - ISAE 3000 §A99: direct evidence > corroborated evidence.

Revision: 0023_M22
Revises:  0021_M20
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0023_M22"
down_revision: str = "0021_M20"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Replace UPDATE-permitting reciprocity trigger; add append-only guard."""

    # -------------------------------------------------------------------------
    # 1. Drop the M20 reciprocity trigger (which fired on INSERT OR UPDATE).
    #    The function body is kept unchanged; only the event list changes.
    # -------------------------------------------------------------------------
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_calc_runs_dual_run_reciprocity
            ON ops.calc_runs;
        """
    )

    # -------------------------------------------------------------------------
    # 2. Re-create reciprocity trigger as AFTER INSERT ONLY.
    #    DEFERRABLE INITIALLY DEFERRED: fires at COMMIT so both rows of a
    #    dual-track pair can be inserted inside a single transaction with
    #    pre-generated UUIDs without a chicken-and-egg violation.
    #    The OR UPDATE OF dual_run_id clause is intentionally absent.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_calc_runs_dual_run_reciprocity
        AFTER INSERT ON ops.calc_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION ops.enforce_dual_run_reciprocity();
        """
    )

    # -------------------------------------------------------------------------
    # 3. Create append-only mutation-deny function + trigger for ops.calc_runs.
    #    Modelled on ops.deny_emissions_mutation() which guards
    #    calc.emissions_consolidated.
    #    BEFORE UPDATE OR DELETE: fires immediately when the statement executes,
    #    before any row is changed.  No carve-out for dual_run_id transitions.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ops.deny_calc_runs_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'ops.calc_runs is append-only (Q2.compliance + methodology §7). '
                'UPDATE and DELETE are forbidden. '
                'Use a new INSERT row for corrections or restatements.'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_deny_calc_runs_mutation
        BEFORE UPDATE OR DELETE ON ops.calc_runs
        FOR EACH ROW
        EXECUTE FUNCTION ops.deny_calc_runs_mutation();
        """
    )


def downgrade() -> None:
    """Remove append-only guard; restore M20 INSERT OR UPDATE reciprocity trigger."""

    # 1. Drop append-only mutation trigger + function.
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_deny_calc_runs_mutation
            ON ops.calc_runs;
        """
    )
    op.execute(
        "DROP FUNCTION IF EXISTS ops.deny_calc_runs_mutation();"
    )

    # 2. Drop the INSERT-only reciprocity trigger we created above.
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_calc_runs_dual_run_reciprocity
            ON ops.calc_runs;
        """
    )

    # 3. Restore the original M20 trigger (INSERT OR UPDATE OF dual_run_id).
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_calc_runs_dual_run_reciprocity
        AFTER INSERT OR UPDATE OF dual_run_id ON ops.calc_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION ops.enforce_dual_run_reciprocity();
        """
    )
