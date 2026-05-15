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

### Q2 — Decision (compliance-agent)

**Decision**: **Mandate pre-generated-UUID two-row insert pattern.** The back-fill UPDATE pattern is rejected; both `ops.calc_runs` rows must be inserted with pre-generated UUIDs and reciprocal `dual_run_id` values in a single INSERT batch within one transaction. No UPDATE statement may touch `ops.calc_runs` rows after insertion.

**Verdict**: **APPROVED** (conditional on the implementation requirements below being adopted by backend-agent and test-agent before merge).

**Rationale**:

- **Project's existing append-only invariant on `ops.calc_runs`** (methodology.md §7, Audit Trail Integrity): the table participates in the append-only family enforced by `ops.deny_emissions_mutation()`. Permitting a back-fill UPDATE — even within the same transaction — creates a precedent that erodes the invariant, requires a carve-out in the RLS/trigger policy (`UPDATE` allowed when `dual_run_id` transitions from NULL to non-NULL), and forces every future auditor to verify that no other column was mutated in the same statement. Eliminating the UPDATE path entirely is the only mechanically enforceable rule.
- **GDPR Art. 5(1)(d) "accuracy" + Art. 30 records-of-processing**: the records-of-processing guarantee is "what data the controller held at time T". A row that briefly exists with `dual_run_id IS NULL` and is then mutated leaves no contemporaneous evidence that the NULL state ever existed in audit log replays; conversely a verifier reading WAL/CDC streams would see two distinct states for the same primary key, complicating the Art. 30 narrative. Pre-generated UUIDs guarantee that every persisted state of a `calc_runs` row is its FINAL state.
- **Reg. UE 2018/2067 Art. 6 (verifier traceability)**: Art. 6 requires the verifier to obtain evidence of the calculation chain. A pair of rows that were INSERTed atomically with reciprocal FKs is self-evident; a pair where one row was UPDATEd requires the verifier to also inspect transaction logs to confirm the UPDATE happened inside the same TX as the second INSERT. Self-evident evidence > evidence requiring log forensics.
- **ISAE 3000 §A99 "sufficient appropriate audit evidence"**: §A99 weights "evidence obtained directly" higher than "evidence requiring corroboration". An immutable INSERT-only pair is direct; an INSERT-then-UPDATE pair requires corroborating the transactional boundary, lowering evidence quality.
- **CSRD / ESRS E1 §50–§55**: the methodology disclosure must describe how dual-track reconciliation is evidenced. "Both rows inserted atomically with reciprocal FKs" is a one-sentence disclosure; "row A is inserted, row B is inserted, row A is then updated to point to row B, all within a single TX with append-only carve-out X" is a four-sentence disclosure with a carve-out that itself must be justified. Disclosure parsimony reduces audit-finding surface.
- **10-year retention impact**: `pg_dump`-based archival snapshots taken between the two operations of the back-fill pattern (e.g., a scheduled snapshot landing mid-TX is impossible, but a logical replication subscriber lagging is not) could capture the NULL state. Pre-generated UUIDs eliminate this class of replication-lag artefact entirely.

**Implementation requirements (backend-agent)**:

- Public dual-track entry point (`POST /api/v1/calc/run-dual` per methodology §11.1) MUST generate both UUIDs in Python (`uuid.uuid4()`) BEFORE any DB call.
- `_persist_emissions(...)` MUST accept `run_id: uuid.UUID` as an explicit parameter (no DB-side `DEFAULT gen_random_uuid()` reliance for the dual-track path).
- Both INSERTs MUST occur inside a single `BEGIN … COMMIT` block; recommend a single `INSERT … VALUES (…), (…)` multi-row statement or two sequential INSERTs with `autocommit=False` and a single `commit()` call at the end.
- No `UPDATE ops.calc_runs` statement may exist anywhere in `calc_persistence.py`. Add a code-level guard: `grep -RnE "UPDATE\s+(ops\.)?calc_runs"` in pre-commit returns zero matches.
- The RLS / trigger policy `ops.deny_emissions_mutation()` MUST be extended to `ops.calc_runs` denying both UPDATE and DELETE, with NO carve-out for `dual_run_id`. Document in migration `0019_M18_calc_runs_dual_run_id.py` header comment.
- Single-track (CSRD-only) runs continue to INSERT one row with `dual_run_id = NULL`. NULL on insert is permitted; NULL→non-NULL transition is forbidden.
- `correlation_id` and `calc_timestamp` MUST be identical across both rows of a pair to evidence atomic provenance (factor_source / factor_version / gwp_set may legitimately differ across `regulatory_stream`).

**Test requirements (test-agent)**:

- Integration test asserting that attempting `UPDATE ops.calc_runs SET dual_run_id = … WHERE id = …` raises a permission / trigger error (proves the append-only policy is mechanically enforced, not merely conventional).
- Integration test asserting that on dual-track run, both rows are visible in a single `SELECT … FOR SHARE` snapshot — i.e., neither row was ever visible to another transaction with `dual_run_id IS NULL`.
- Integration test asserting reciprocity post-insert: `a.dual_run_id = b.id AND b.dual_run_id = a.id AND a.regulatory_stream <> b.regulatory_stream AND a.tenant_id = b.tenant_id AND a.anno = b.anno AND a.correlation_id = b.correlation_id`.
- Negative test: simulate a partial failure (e.g., raise in the second INSERT) and assert that the first INSERT is rolled back (no orphan with `dual_run_id IS NULL` persists).
- Logical-replication / WAL test (or unit-level mock thereof) asserting that no intermediate row state with `dual_run_id IS NULL` is ever published for a dual-track run.
- Pre-commit / CI grep guard test: a meta-test that fails if any future PR introduces an `UPDATE … calc_runs` statement under `src/`.


### Q4 — Decision (data-quality-agent)

**Rule name**: `iano_dual_track_pairing_complete`

**Severity**: DQ-CRIT (blocking)

**Justification**: The sustainability-expert-agent decision on Q1 establishes that `dual_run_id`
is the sole auditable linkage between a CSRD ESRS E1 calc run and its paired EU ETS Phase IV
calc run for Annex I installations (IANO). If that linkage is absent or broken, any downstream
`value_tco2e` published under `regulatory_stream='CSRD_ESRS_E1'` cannot be reconciled with
the verifier-facing ETS figure as required by Reg. UE 2018/2067 Art. 6 and CSRD ESRS E1 §53–§55.
A WARNING would allow the pipeline to publish a non-reconcilable disclosure — unacceptable
under both frameworks. DQ-CRIT is the only appropriate severity.

**Detection logic**:

```sql
-- Step 1: identify all CSRD rows for IANO tenants in the current reporting batch.
-- "IANO tenant" = tenant whose installation registry includes at least one Annex I
-- installation (methodology §11; tenant_flag = 'HAS_IANO' or equivalent).

WITH csrd_rows AS (
    SELECT
        cr.id           AS calc_run_id,
        cr.tenant_id,
        cr.anno,
        cr.dual_run_id,
        cr.regulatory_stream
    FROM ops.calc_runs cr
    WHERE cr.regulatory_stream = 'CSRD_ESRS_E1'
      AND cr.anno             = :reporting_anno        -- bound per batch
      AND cr.tenant_id        IN (                     -- IANO tenants only
              SELECT tenant_id
              FROM   ops.tenant_installation_registry
              WHERE  annex_i_flag = TRUE
          )
),

-- Step 2: for each CSRD row check that dual_run_id resolves to
-- a EU_ETS_PHASE_IV row sharing (tenant_id, anno).

paired AS (
    SELECT
        c.calc_run_id,
        c.tenant_id,
        c.anno,
        c.dual_run_id,
        p.regulatory_stream AS paired_stream
    FROM csrd_rows c
    LEFT JOIN ops.calc_runs p
           ON p.id              = c.dual_run_id
          AND p.regulatory_stream = 'EU_ETS_PHASE_IV'
          AND p.tenant_id        = c.tenant_id
          AND p.anno             = c.anno
)

-- Step 3: surface unpaired rows (dual_run_id IS NULL OR join found nothing).
SELECT *
FROM   paired
WHERE  paired_stream IS NULL      -- covers both NULL dual_run_id and stale FK
   OR  dual_run_id   IS NULL;
```

Coverage threshold: **100 %** — every CSRD ESRS E1 row for an IANO tenant must be
paired. A tenant-level override (e.g. `dq_overrides.iano_pairing_threshold`) MAY lower
this to a minimum of 95 % during a defined transition window, but only with explicit
ComplianceAgent approval and a documented expiry date. The override must itself be
recorded in `ops.dq_overrides` and surfaced in the DQ report.

**Output when check fails**:

```json
{
  "rule":          "iano_dual_track_pairing_complete",
  "rule_id":       "DQ-CRIT-06",
  "severity":      "CRIT",
  "blocks_pipeline": true,
  "tenant_id":     "<tenant_id>",
  "anno":          "<N>",
  "affected_count": 3,
  "coverage_ratio": 0.70,
  "sample_rows": [
    {"calc_run_id": "<uuid>", "dual_run_id": null,    "anno": 2024},
    {"calc_run_id": "<uuid>", "dual_run_id": "<uuid>", "anno": 2024,
     "note": "dual_run_id present but target row not EU_ETS_PHASE_IV"}
  ],
  "remediation": "Re-run or register the EU ETS Phase IV calc for anno=N and set dual_run_id on the CSRD run before re-triggering the publish pipeline."
}
```

The JSON envelope is emitted to the orchestrator's DQ findings sink
(`calc.dq_findings` table, `rule_id='DQ-CRIT-06'`, `blocks_pipeline=TRUE`) and
forwarded to ComplianceAgent for audit trail. The publish pipeline (calc/publish
endpoint) MUST NOT proceed until `affected_count = 0` for the current batch.

**Scope and exemptions**:

- **Exempt — single-track tenants**: tenants that have NO Annex I installation
  (i.e. `annex_i_flag = FALSE` in `ops.tenant_installation_registry` for all
  installations of that tenant). For these tenants `dual_run_id IS NULL` is valid
  and the check is **skipped entirely** (not evaluated).
- **Exemption detection mechanism**: the check queries
  `ops.tenant_installation_registry WHERE annex_i_flag = TRUE AND tenant_id = :tid`
  before evaluating any rows. If that query returns zero rows the check exits
  immediately with `block_level='OK'` and a note
  `"skipped: no Annex I installation for tenant"`.
  The registry is owned by DataEngineerAgent / ArchitectAgent and must be populated
  as part of tenant onboarding (methodology §11). The DQ check MUST NOT infer IANO
  status from the data rows themselves — doing so would allow a misconfigured tenant
  to silently bypass the check.
- **Scope 3 rows**: the check applies only to `ops.calc_runs` rows, not to individual
  emission line items. Scope 3 sub-categories do not have a parallel ETS obligation
  and are out of scope for this rule.

**Test plan**:

1. **Unit — IANO tenant, both tracks present and correctly paired (passes)**:
   - Fixture: tenant `T1` with `annex_i_flag=TRUE`; two `calc_runs` rows for `anno=2024`:
     row A (`regulatory_stream='CSRD_ESRS_E1'`, `dual_run_id=<B.id>`) and row B
     (`regulatory_stream='EU_ETS_PHASE_IV'`, `dual_run_id=<A.id>`).
   - Expected: check returns `(True, [])`, no DQ-CRIT finding emitted.

2. **Unit — IANO tenant, CSRD row exists but no ETS run (fails)**:
   - Fixture: tenant `T1` with `annex_i_flag=TRUE`; one `calc_runs` row
     (`regulatory_stream='CSRD_ESRS_E1'`, `dual_run_id=NULL`).
   - Expected: check returns `(False, [finding])` with
     `rule_id='DQ-CRIT-06'`, `severity='CRIT'`, `blocks_pipeline=True`,
     `affected_count=1`.

3. **Unit — IANO tenant, dual_run_id set but target row has wrong regulatory_stream (fails)**:
   - Fixture: tenant `T1` with `annex_i_flag=TRUE`; row A
     (`regulatory_stream='CSRD_ESRS_E1'`, `dual_run_id=<B.id>`) and row B
     (`regulatory_stream='CSRD_ESRS_E1'`  -- same stream, wrong pairing).
   - Expected: check returns `(False, [finding])` with a note that the FK target
     exists but `paired_stream != 'EU_ETS_PHASE_IV'`.

4. **Unit — non-IANO tenant, single CSRD run (skipped/passes)**:
   - Fixture: tenant `T2` with `annex_i_flag=FALSE`; one `calc_runs` row
     (`regulatory_stream='CSRD_ESRS_E1'`, `dual_run_id=NULL`).
   - Expected: check returns `(True, [])` with
     `block_level='OK'` and skip note — no finding emitted.

5. **Unit — transition-window tenant override (passes at reduced threshold)**:
   - Fixture: tenant `T3` with `annex_i_flag=TRUE`; `dq_overrides` entry
     `{rule='iano_dual_track_pairing_complete', min_coverage=0.95, expiry='2025-12-31'}`;
     9 of 10 CSRD rows paired (coverage=0.90 < 0.95 < 1.00).
   - Expected: check returns `(False, [finding])` — the override lowers the threshold
     to 0.95 but 0.90 is still below it, so DQ-CRIT is still emitted.
   - Verify separately that coverage=0.96 with the same override returns `(True, [])`.
