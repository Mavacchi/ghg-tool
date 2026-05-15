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

### Q1 — Decision (sustainability-expert-agent)

**Decision**: **A — I overturn the conservative pick.** A dedicated `dual_run_id UUID NULL`
column on `ops.calc_runs` is required. The join-based reconstruction proposed in (B) is
not deterministic and does not satisfy verifier traceability under Reg. UE 2018/2067 Art. 6.

**Normative rationale**:

- **Reg. UE 2018/2067 Art. 6 (Verifier traceability)**: the verifier must be able to confirm
  that the AR5/ETS tCO2e values and the AR6/CSRD tCO2e values for installation IANO were
  produced from the **same raw activity-data snapshot**. The composite key proposed in (B)
  joins on `(tenant_id, anno, regulatory_stream)` — but each track gets its OWN
  `correlation_id` (per the existing orchestrator contract and `methodology.md` §11.1).
  Two co-existing runs for year N with `regulatory_stream='CSRD_ESRS_E1'` and
  `regulatory_stream='EU_ETS_PHASE_IV'` can be paired only by temporal proximity or by
  human inspection, neither of which is auditable. If the CSRD track is re-run after a
  factor update (FR-21 / §5) without re-running the ETS track, the "natural" join now
  associates a newer CSRD `correlation_id` with an older ETS `correlation_id` that was
  derived from a different raw snapshot — silently breaking Art. 6 reproducibility.
- **GHG Protocol Corporate Standard Ch.5 (recalculation / base-year)**: §5 requires that
  recalculation events be linked to the prior baseline in a way that is "traceable and
  unambiguous". A re-run of one track creates exactly the recalculation pattern Ch.5
  addresses; without a `dual_run_id` FK the pairing is ambiguous on its face.
- **CSRD ESRS E1 §50–§55 (climate metrics traceability)**: §50 requires undertakings to
  disclose the methodologies and assumptions used; §53–§55 require the **reconciliation**
  between disclosed metrics and any parallel regulatory reporting (e.g., EU ETS) to be
  evidenced. A FK column is the canonical relational way to evidence a pairwise
  reconciliation; the join-based approach evidences only a co-existence relationship.
- **GHG Protocol Scope 2 Guidance (2015) Ch.11 (instrument hierarchy and recordkeeping
  analogy)**: the Guidance requires the MB instrument records to be linked to the specific
  reporting period and the specific load — a precedent for explicit relational linkage
  between an emission claim and its supporting evidence row. Dual-track linkage is the same
  pattern applied across `regulatory_stream` boundaries.
- **Database design (verifier query ergonomics)**: an indexed `dual_run_id` FK gives the
  verifier a one-row-pair `SELECT … WHERE dual_run_id = :rid` query. The (B) approach
  forces the verifier to write a temporal-window join with no deterministic answer when
  multiple runs exist for the same year. Verifier ergonomics is itself a Reg. 2018/2067
  Art. 6 consideration (the verifier must be able to "obtain sufficient evidence" — opaque
  joins are not sufficient evidence under ISAE 3000 §A99 either).
- **Methodology document already commits to this**: `docs/methodology.md` §11.1 cites
  Reg. UE 2018/2067 Art. 6 and asserts "both tracks must derive from the same raw ingestion
  snapshot." That assertion is enforceable only if the two `ops.calc_runs` rows reference
  each other. Without the FK, the methodology statement is aspirational, not auditable.

**Code / schema implications (option A path)**:

1. New migration `alembic/versions/0019_M18_calc_runs_dual_run_id.py`:
   - `op.add_column('calc_runs', sa.Column('dual_run_id', sa.UUID(as_uuid=True), nullable=True), schema='ops')`
   - Self-referential FK: `sa.ForeignKey('ops.calc_runs.id', ondelete='SET NULL')`.
     NULL is permitted because single-track (CSRD-only) runs are still valid for tenants
     with no EU ETS installation (only IANO is Annex I per methodology §11).
   - Index `ix_calc_runs_dual_run_id` on `(dual_run_id)` for verifier join performance.
   - CHECK constraint: `dual_run_id IS NULL OR dual_run_id <> id` (no self-reference).
   - Recommended (deferred to integrity review): a partial constraint enforcing that if
     `dual_run_id IS NOT NULL` then the two paired rows share `(tenant_id, anno)` and have
     **different** `regulatory_stream` values, and that the relation is reciprocal. This
     is a trigger, not a CHECK, so flag as a follow-up.
2. `src/ghg_tool/application/services/calc_persistence.py`:
   - Re-introduce `dual_run_id: uuid.UUID | None = None` on the public
     `run_calc_and_persist(...)` signature.
   - Thread it through to `_persist_emissions(...)` (this is the bug the WIP missed).
   - Add `dual_run_id` binding to `_INSERT_CALC_RUN` and to its parameter dict.
   - Update the public dual-track entry point (`POST /api/v1/calc/run-dual` per
     methodology §11.1) to: (a) run track 1, obtain `run1_id`; (b) run track 2 with
     `dual_run_id=run1_id`; (c) update track 1 row to set `dual_run_id=run2_id` inside the
     same transaction wrapping the back-fill, OR insert both rows in a single transaction
     with pre-generated UUIDs. Either pattern is acceptable; the second is preferred
     because it preserves the append-only spirit of `ops.calc_runs` (no UPDATEs).
3. Unit + integration tests:
   - Unit: assert `dual_run_id` is bound when present and is NULL when single-track.
   - Integration (against real Postgres in the M10/M11 test fixture): assert FK validity,
     reciprocity (both rows reference each other), and that `regulatory_stream` differs.

**Acceptance criteria for closing Q1**:

- Migration `0019_M18_calc_runs_dual_run_id.py` merged on `main`, with downgrade tested.
- `calc_persistence.py` re-threads `dual_run_id` end-to-end; mypy + unit tests green.
- Integration test in `tests/integration/test_calc_persistence_dual_track.py` covering:
  (i) single CSRD run → `dual_run_id IS NULL`; (ii) dual-track run → both rows reference
  each other; (iii) re-run of one track creates a NEW pair (the old pair is preserved
  via the immutable `ops.calc_runs` row).
- `docs/methodology.md` §11.1 amended to state the FK linkage explicitly (TODO — do NOT
  edit in this PR per instructions; route to documentation-agent).
- `docs/requirements.md` FR-34 acceptance criterion explicitly mentions `dual_run_id`
  (TODO — same).
- Verifier query example added to `docs/methodology.md` §7 (Audit Trail Integrity):
  `SELECT a.*, b.* FROM ops.calc_runs a JOIN ops.calc_runs b ON a.dual_run_id = b.id
   WHERE a.id = :rid` — one-row-pair reconciliation. (TODO.)
- ReviewerAgent sign-off on the migration; ComplianceAgent sign-off that the relational
  evidence satisfies Reg. UE 2018/2067 Art. 6 + ISAE 3000 §A99.

**Open downstream questions to route further**:

1. **DataEngineerAgent / ArchitectAgent**: the reciprocity constraint (each side of the
   pair points to the other) is most cleanly enforced by a deferrable trigger; confirm
   that the existing `ops.deny_emissions_mutation()` pattern can be extended to
   `ops.calc_runs` without conflicting with the audit-row append-only invariant.
2. **ComplianceAgent**: confirm that a one-sided NULL (back-fill of track 1's `dual_run_id`
   after track 2 inserts) is acceptable within a single transaction, OR mandate the
   pre-generated-UUID two-row insert pattern. Either is auditable; choosing one removes
   ambiguity for ReviewerAgent.
3. **RequirementsAgent**: should FR-34 explicitly require that re-running a single track
   AFTER an existing dual-track pair was filed creates a NEW pair (i.e., is the prior
   pair frozen even when one track is restated)? Methodology §11.1 implies yes (snapshot
   parity), but the requirement text is silent.
4. **DataQualityAgent**: define a DQ-CRIT check that for any IANO emission row with
   `regulatory_stream='CSRD_ESRS_E1'` and `anno=N` there exists a paired
   `EU_ETS_PHASE_IV` row reachable via `dual_run_id`. Without this, the FK exists but is
   not enforced as a business rule.
