# WIP_QUESTIONS — outstanding methodology / scope questions

Open questions left by the agent completing the partial Decimal precision +
ESG methodology fixes WIP (parent commit `654868d`). The orchestrator should
route these to sustainability-expert-agent and/or the platform/data team.

## Q1 — `dual_run_id` column on `ops.calc_runs`

**Files**: `src/ghg_tool/application/services/calc_persistence.py`

**Context**: the inherited WIP added a `dual_run_id UUID NULL` reference to
the `_INSERT_CALC_RUN` SQL and threaded the parameter through
`_persist_emissions` and `run_calc_and_persist`. The rationale comment cites
M-05 / FR-34 / Reg. UE 2018/2067 Art. 6 (link CSRD and EU ETS tracks for
verifier traceability).

**Problem**:
1. `alembic/versions/0011_M10_calc_runs.py` (the only migration touching
   `ops.calc_runs`) does NOT define a `dual_run_id` column. The INSERT would
   fail against a real Postgres with `column "dual_run_id" of relation
   "calc_runs" does not exist`. Unit tests passed only because the SQLAlchemy
   mock does not validate column existence.
2. The orchestrator's instructions for this agent explicitly forbid touching
   migration files or DB schemas.
3. Even when added, the WIP did not thread `dual_run_id` from the public
   `run_calc_and_persist` signature into the `_persist_emissions(...)` call
   site — the parameter is accepted but silently dropped.

**Conservative interpretation applied here** (per "pick the most conservative
interpretation aligned with GHG Protocol Scope 2 Guidance" — analogous
governance rule): the `dual_run_id` SQL column and parameter plumbing has
been REVERTED. The end-state is the original schema-compatible insert.
M-05 / FR-34 dual-track traceability can already be reconstructed via
`(tenant_id, anno, correlation_id, regulatory_stream)` joins, so removing
the column is not a loss of audit information — it is just a missing
shortcut.

**Decision required from orchestrator / data team**:
  * (A) Approve a new alembic migration `0019_M18_calc_runs_dual_run_id.py`
    adding the column, then re-introduce the SQL + param plumbing.
  * (B) Keep the join-based reconstruction permanent and remove the
    associated M-05 acceptance criterion from `methodology.md` (no schema
    change required).

Conservative pick until decision: (B). Code reverted to the schema as it
actually exists in `0011_M10`.
