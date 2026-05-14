# GHG Methodology — Ceramic Tile Manufacturer

**Version**: 1.0.0 (Phase 9 — initial publication incorporating Phase 7/8 changes)
**Date**: 2026-05-14
**Status**: APPROVED — reflects SustainabilityExpertAgent methodology_validation.md v1.0.0 and
Phase 7/8 security and data-model decisions
**References**:
- `docs/methodology_validation.md` v1.0.0 (SustainabilityExpertAgent — authoritative source)
- `docs/requirements.md` v1.2.2 (APPROVED)
- `docs/architecture.md` v1.0.0 (Phase 4)
- GHG Protocol Corporate Standard (2004) + Scope 2 Guidance (2015) + Scope 3 Standard (2011)
- IPCC AR6 WG1 Chapter 7 SM Table 7.SM.7
- IPCC 2006 Guidelines V3 Ch.2 §2.5.1.3 Table 2.1
- CSRD Directive 2022/2464/EU; ESRS E1 (adopted 2023)
- EU ETS Phase IV: Directive 2003/87/EC; MRR Regulation 2018/2066 as amended by 2023/2122

This document is the canonical methodology reference for v1. Every calculation parameter
derives from methodology_validation.md unless otherwise cited. This document does not
introduce new methodology; it records and structures existing validated decisions.

---

## 1. Organisational Boundary

**Method**: Operational control per GHG Protocol Corporate Standard Chapter 4. The company
accounts for 100% of GHG emissions from operations over which it exercises operational control.

**Sites in scope**:

| Codice Sito | Role | Scope notes |
|---|---|---|
| IANO | Main production site; sole site with CaCO3 decarbonation process; EU ETS Annex I Activity 17 | Scope 1 combustion + process; Scope 2 LB+MB; Scope 3 WTT/T&D |
| VIANO | Secondary production | Scope 1 combustion; Scope 2 LB+MB |
| VIANO_GARGOLA | Secondary production; gas connection commissioned 2025 | Scope 1 combustion (2024: ETL-synthesised zero row); Scope 2 LB+MB |
| CASALGRANDE | Secondary production | Scope 1 combustion; Scope 2 LB+MB |
| FIORANO | Secondary production | Scope 1 combustion; Scope 2 LB+MB |
| SASSUOLO | Secondary production; sole site with non-GO grid electricity in 2024 (46,786 kWh) | Scope 1 combustion; Scope 2 LB+MB |
| FRASSINORO | Secondary production; second largest electricity consumer (8,716,707 kWh 2024) | Scope 1 combustion; Scope 2 LB+MB |

**Entities explicitly excluded**: no joint ventures; no non-consolidated participations
(confirmed by user 2026-05-13). Parent or holding companies outside operational control are
excluded unless separately confirmed.

**Base year**: 2024 (all 7 sites, consolidated).

---

## 2. Reporting Scope Definitions

### Scope 1 — Direct emissions

| Sub-category | Method | Factor source | Sites |
|---|---|---|---|
| Gas Naturale combustion (Sm3) | Activity × DEFRA fuel EF | DEFRA 2025 edition, AR6 GWP | All 7 |
| Gasolio combustion (litres) | Activity × DEFRA fuel EF | DEFRA 2025 edition, AR6 GWP | All 7 |
| Benzina combustion (litres) | Activity × DEFRA fuel EF | DEFRA 2025 edition, AR6 GWP | SASSUOLO only |
| Processo_Decarb — CaCO3 decarbonation (kg) | Stoichiometric: 0.4397 tCO2/t CaCO3 | IPCC 2006 V3 §2.5.1.3 Table 2.1 | IANO only |
| Fugitive HFC | Declared zero (OI-10 closed 2026-05-13) | N/A | All 7 (zero-line disclosure) |

**Scope 1 process formula**:
```
tCO2 = kg_CaCO3 / 1000 * 0.4397
```
No CH4 or N2O component. GWP conversion is 1.0 (CO2 is the reference gas). Classified as
"Process emissions" in all outputs, reported separately from combustion in ESRS E1-6 §44(a).

**LOI uncertainty**: the CaCO3 mass is estimated via Loss On Ignition (LOI = 3.5% of
fired product mass). Typical uncertainty bound: +/-10-20% relative. Flagged as
DQ-WARN-02; disclosed in PDF report. Upgrade path to XRF measurement (Tier 2) recommended
for Year 1 improvement plan. Source: methodology_validation.md §6.4.

### Scope 2 — Indirect energy emissions

Dual reporting is mandatory and non-negotiable per GHG Protocol Scope 2 Guidance. LB and
MB values are NEVER aggregated; they are always reported as separate, labelled values.

| Accounting method | Factor | Source | Notes |
|---|---|---|---|
| Location-based (LB) | ISPRA Italia grid emission factor | ISPRA Rapporto 413/2025 (2023 data; 2024 vintage pending — use 2023 with documented vintage offset if 2024 not published at reporting date) | All kWh consumed per site per year |
| Market-based (MB) — GO volumes | 0 tCO2e/MWh | Conditional on GO Quality Criteria validation (OI-4, CG-08) | Volumes covered by GSE Garanzia d'Origine certificates satisfying all 8 Scope 2 Quality Criteria |
| Market-based (MB) — residual | AIB Italian Residual Mix 2024 | AIB European Residual Mix 2024 (Grexel Systems, published 2025-05-30) | Non-GO kWh (SASSUOLO 2024: 46,786 kWh EE_Acquistata_Grid) |

**GO Quality Criteria**: All 8 criteria per GHG Protocol Scope 2 Guidance (2015) Ch.7 must
be verified by the data steward per per-certificate checklist (methodology_validation.md §2.4)
before MB = 0 is published. Until verified, residual mix applies. CG-08 gates the MB claim.

### Scope 3 — Value chain emissions

Nine material categories identified; five categories disclosed as "not applicable" or
"not material" with rationale per ESRS E1-6 §44(c) and GHG Protocol Scope 3 Standard Ch.5.

**Material categories (activity data present)**:

| Category | Method | Factor source |
|---|---|---|
| Cat 1 — Purchased goods and services | Mass-based (ecoinvent v3.10); spend-based (EXIOBASE 3 / CDP sector ratios) | ecoinvent v3.10 primary; supplier EPD override where available |
| Cat 2 — Capital goods | Spend-based | EXIOBASE 3 NACE C.28 / C.27 |
| Cat 3 — Fuel- and energy-related (WTT + T&D) | Activity-based; fuel quantity = Sigma Scope 1 per FR-11 (NOT from Cat 3 CSV) | DEFRA 2025 (WTT); ISPRA / Terna T&D loss rate |
| Cat 4 — Upstream transportation | Distance-based (tkm x DEFRA mode-specific freight factor) | DEFRA 2025 (road HGV, rail, sea bulk carrier) |
| Cat 5 — Waste generated in operations | Mass-based by disposal route | DEFRA 2025 (landfill, recycling) |
| Cat 6 — Business travel | Spend-based | DEFRA 2025 spend factors (GBP-denominated; EUR/GBP PPP conversion documented) |
| Cat 7 — Employee commuting | Distance-based; FTE = HR headcount (2024: 506, 2025: 484, confirmed 2026-05-13) | DEFRA 2025 average car |
| Cat 9 — Downstream transportation | Distance-based (tkm); load factor 27 t | DEFRA 2025 (HGV road, transoceanic sea) |
| Cat 12 — End-of-life treatment of sold products | Mass-based; 30% landfill / 70% recycling (proxy) | ecoinvent v3.10 (inert mineral landfill; construction-waste recycling) |

**Non-material categories (explicit zero-line disclosure in all outputs)**:

| Category | Status | Rationale |
|---|---|---|
| Cat 8 | Not applicable | All leased assets are within the operational-control boundary and accounted for in Scope 1/2 |
| Cat 10 | Not applicable | Finished tiles undergo no industrial processing between sale and end-use |
| Cat 11 | Omitted — Immaterial | Ceramic tiles are passive products with no operational energy consumption during use phase (FR-18) |
| Cat 13 | Not applicable | The company is not a lessor of operational assets |
| Cat 14 | Not applicable | No franchise network |
| Cat 15 | Not applicable | Non-financial undertaking; no investment portfolio in scope (OI-8 confirmed by user 2026-05-13) |

---

## 3. GWP Set and Emission Factor Catalog

### GWP values in use

| Set | CH4 GWP100 | N2O GWP100 | Application | Source |
|---|---|---|---|---|
| AR6 (default) | 27.9 | 273 | CSRD ESRS E1-6 primary output | IPCC AR6 WG1 Ch.7 SM Table 7.SM.7 |
| AR5 | 28 (no climate-carbon feedback) | 265 | EU ETS Phase IV parallel output for IANO (FR-34, FR-19) | IPCC AR5 WG1 Ch.8 Table 8.7; MRR Regulation 2018/2066 as amended by 2023/2122 |

GWP sets are **never mixed within a single report run** (FR-19). AR6 is the default. AR5
runs are a separate, clearly labelled output (`regulatory_stream = EU_ETS_PHASE_IV`).
AR4 values (CH4=25, N2O=298) are NOT used.

### Factor source cascade

Order of precedence per FR-04 and methodology_validation.md §4.3:

1. Supplier-specific EPD (ISO 14025 + EN 15804 A2) — where available, current, and product-covering
2. ecoinvent v3.10 (mass-based Cat 1 raw materials)
3. EXIOBASE 3 / CDP sector ratios (spend-based Cat 1 services, Cat 2, Cat 6)
4. DEFRA / DESNZ 2025 (transport, WTT, business travel, waste)
5. ISPRA (Italian grid LB)
6. AIB Italian residual mix 2024 (Scope 2 MB residual)
7. IPCC stoichiometric (Scope 1 process emissions)

Every factor catalog entry carries: `factor_id`, `source`, `version`, `valid_from`, `gwp_set`,
`value`, `unit` per FR-04. Factor entries are immutable post-publish; updates create a new
version.

---

## 4. Biogenic CO2 Treatment (ADR-007 Confirmed)

**Biogenic CO2 is disclosed in a separate column and is NEVER included in Scope 1/2/3 totals.**

Per GHG Protocol Corporate Standard §4.5 and ESRS E1-7, biogenic CO2 from the combustion
or decomposition of biological materials (e.g. biogenic carbon stored in cardboard packaging,
wooden pallets) is reported as a supplementary disclosure, not as part of the gross GHG
inventory.

**Implementation**:
- `calc.emissions_consolidated.co2_biogenic_tonne` stores the biogenic CO2 component.
- `calc.emissions_consolidated.co2_fossil_tonne` stores the fossil CO2 component.
- `tco2e` contains fossil-origin CO2e only; biogenic carbon is excluded from `tco2e`.
- The PDF E1-7 sub-template renders `co2_biogenic_tonne` with an explicit caption:
  "Biogenic CO2 — NOT included in Scope 1/2/3 totals."
- The Excel biogenic memo sheet (`write_biogenic_memo_sheet`) discloses the biogenic
  figures with an equivalent caption.

**Normative basis**: GHG Protocol Corporate Standard §4.5 ("Biogenic carbon"); ESRS E1-7
§49 (disclosure of biogenic carbon flows).

---

## 5. Policy of Data Immutability

The tables `calc.emissions_consolidated`, `calc.dq_findings`, `calc.dlq`, and
`calc.audit_log` are **append-only**. No UPDATE or DELETE is permitted under any
circumstances outside the designated correction stored procedure.

### Enforcing trigger

`trg_emissions_deny_mutation` (created in migration M1) fires BEFORE UPDATE OR DELETE on
`calc.emissions_consolidated`. The function `ops.deny_emissions_mutation()` raises SQLSTATE
P0001 on any DELETE. On UPDATE it additionally checks the session GUC
`app.correction_in_progress`; if the GUC is not set to `'true'` the UPDATE is rejected.
Even inside a correction, only the columns `valid_to`, `superseded_by`, and `reason_code`
may change; any modification to `tco2e`, `factor_id`, `gwp_set`, `scope`, `anno`, or
`codice_sito` raises an exception.

### Correction workflow (FR-21)

When an error is identified in emission row R1:

1. Insert a new row R2 with corrected values and all mandatory metadata fields populated.
2. Call `calc.fn_emit_correction(p_predecessor_id := R1.id, p_new_id := R2.id, p_reason_code := '<code>')`.
3. The stored procedure (SECURITY DEFINER) sets `app.correction_in_progress = 'true'`
   locally within the transaction, then executes the restricted UPDATE on R1:
   `valid_to = now(), superseded_by = R2.id, reason_code = <code>`.
4. R1 remains accessible with `valid_to IS NOT NULL`. R2 is the active record
   (`valid_to IS NULL`).

### Canonical reason codes

| Code | Trigger condition |
|---|---|
| `DATA_ERROR` | Input data error identified post-insert |
| `FACTOR_UPDATE` | Emission factor revised in the catalog (new version) |
| `BOUNDARY_CHANGE` | Organisational boundary changed (site acquisition or divestiture) |
| `METHODOLOGY_REVISION` | Methodology changed (e.g. GWP set change, calculation approach change) |
| `RESTATEMENT_>5PCT` | Recalculation triggered because the change exceeds the 5% significance threshold per FR-26 |

---

## 6. Recalculation Policy (FR-26 — GHG Protocol §5)

**Significance threshold**: A structural change (site acquisition or divestiture) or
methodology change that causes a shift of more than 5% in the base-year (2024)
Scope 1+2 total tCO2e triggers mandatory base-year recalculation.

**Recalculation procedure**:

1. The recalculation inserts new rows with corrected values for all affected (scope, site, year) combinations.
2. Each predecessor row receives `valid_to = now()`, `superseded_by = <new_row_id>`,
   and `reason_code` from the canonical set above.
3. Old rows are NEVER deleted. The full correction chain is traversable via the
   `/api/v1/corrections` endpoint.
4. A `recalculation_id` (UUID, stored in `correlation_id` of the recalculation batch)
   links all recalculation rows.

**Mapping of reason codes to GHG Protocol §5 triggers**:

| GHG Protocol §5 trigger | Reason code used |
|---|---|
| Structural change (acquisition, divestiture, outsourcing, insourcing) | `BOUNDARY_CHANGE` |
| Changes in calculation methodology | `METHODOLOGY_REVISION` |
| Discovery of significant errors | `DATA_ERROR` |
| Changes in emission factors | `FACTOR_UPDATE` |
| Any of the above causing > 5% base-year shift | `RESTATEMENT_>5PCT` |

**Normative basis**: GHG Protocol Corporate Standard Chapter 5 ("Setting a GHG Inventory
Base Year").

### Snapshot-based reconciliation (M13)

Carbontrace freezes the consolidated emissions at the moment a CSRD ESRS E1 report (or
EU ETS / interim package) is signed by writing a row to `calc.report_snapshots`. Every
subsequent calc run can be reconciled against the snapshot via
`GET /api/v1/reconciliation/diff`, which returns a per-row delta with a cause
classification (`factor_update`, `data_correction`, `methodology`, `new_row`,
`withdrawn_row`, `unknown`). A restatement is required when either the aggregate
delta exceeds 5% (matches FR-26 / GHG Protocol §5) or any single sub-scope row
exceeds 10% AND the absolute delta is at least 100 tCO2e (CSRD Article 23
"single material item" convention).

Snapshots are append-only; the trigger `trg_report_snapshots_deny_mutation` blocks
UPDATE and DELETE. Snapshot creation is gated to `esg_manager` and writes a
`calc.audit_log` row + emits a `report_snapshot_created` SIEM event in the same
transaction.

---

## 7. Audit Trail Integrity (Phase 8)

### Bitemporal columns

Every row in `calc.emissions_consolidated` carries bitemporal validity markers:

| Column | Type | Semantics |
|---|---|---|
| `valid_from` | TIMESTAMPTZ | UTC timestamp when this row became the valid record (default: `now()` at INSERT) |
| `valid_to` | TIMESTAMPTZ | NULL = currently active; set by the correction procedure when superseded |
| `superseded_by` | UUID FK | NULL = active; points to the replacement row on correction |
| `reason_code` | VARCHAR(40) | NULL on original rows; mandatory on correction rows (one of the 5 canonical codes) |

The partial unique index `ux_emissions_active_natural_key` enforces at most one active row
per (tenant_id, scope, sub_scope, codice_sito, anno, regulatory_stream, gwp_set) combination.

### Point-in-time queries

An auditor can query the state of the emission inventory at any past timestamp T by
selecting rows where `valid_from <= T AND (valid_to IS NULL OR valid_to > T)`. This
supports ISAE 3000 Limited assurance of any historical reporting period.

### Provenance traceability (FR-22)

Every emission row carries: `raw_row_id` (FK to the ingestion staging row), `factor_id`
(FK to `ref.factor_catalog`), `factor_version`, `factor_source`, `gwp_set`, `methodology`,
`calc_timestamp`, `created_by`, `correlation_id`. No unlinked rows are permitted.

---

## 8. Multi-tenant Isolation (Phase 8)

### Row-Level Security (M4)

PostgreSQL RLS policies on `raw.*` and `calc.{emissions_consolidated, dq_findings, dlq, audit_log}`
restrict every SELECT, INSERT, and UPDATE to rows whose `tenant_id` matches the session GUC
`app.tenant_id`. The GUC is set per request by `api/dependencies/session_guc.py` before any
query executes.

### Security-barrier views on materialised views (M7)

PostgreSQL 15 materialised views (`calc.mv_kpi_summary`, `calc.mv_intensity_metrics`) are
independent relations and **do not inherit RLS** from their base tables. This is a
PostgreSQL platform constraint (RLS on MVs is only supported from PG17+).

Migration M7 introduces two `security_barrier=true` views that wrap each materialised view
with an explicit tenant filter:

- `calc.v_kpi_summary` wraps `calc.mv_kpi_summary`
- `calc.v_intensity_metrics` wraps `calc.mv_intensity_metrics`

Both views apply `WHERE tenant_id = current_setting('app.tenant_id', true)::uuid`, using
the same `missing_ok=true` GUC pattern as the M4 RLS policies.

The application DB role `ghg_app` has SELECT on the views and has had SELECT REVOKED on
the underlying materialised views. All application-path queries must go through the
security-barrier views.

The MV refresh job (superuser / migration role) bypasses the REVOKE and refreshes the
underlying MVs directly. This is correct behaviour.

**References**: `alembic/versions/0008_M7_mv_tenant_security.py`; SEC-P0-002.

---

## 9. Refresh-Token Role Re-fetch (SEC-P0-004)

On every `POST /api/v1/auth/refresh` call, the user's current role is re-fetched from
`ref.users JOIN ref.roles` using the `sub` claim of the refresh token, before the new
access token is issued.

This prevents **silent privilege elevation**: if a user's role is changed in `ref.users`
between their initial login and a subsequent refresh, the new access token will carry the
updated role, not the role from the original login session.

The refresh token intentionally carries no `role` claim. The previous implementation that
used `claims.get("role", "data_steward")` as a default was a privilege elevation vector
(any user could obtain a `data_steward` token via /refresh); this has been corrected.

Any refresh attempt for a user with `is_active = False` is rejected with HTTP 401.

**References**: `src/ghg_tool/api/routers/auth.py`; SEC-P0-004.

---

## 10. PII Hygiene in Logs (SEC-P0-005)

All structured log lines emitted by the application are PII-free:

- Usernames are SHA-256 hashed to a 16-character hex prefix before being written to any
  log line: `hashlib.sha256(username.encode()).hexdigest()[:16]`.
- User IDs (UUID) are truncated to 8 characters in log context after the authentication
  step.
- Plaintext passwords are never logged or echoed under any circumstances.
- The `probe_attempt=True` field in log lines for failed login and suspicious refresh
  events allows SIEM systems to aggregate security signals without PII exposure.

**References**: `src/ghg_tool/api/routers/auth.py` (`_hash_username`); SEC-P0-005; SG-07.

---

## 11. EU ETS Phase IV — Dual-track (FR-34)

IANO is confirmed as an Annex I Activity 17 installation (manufacture of ceramic products
by firing). The EU ETS Phase IV MRR Regulation (2018/2066 as amended by 2023/2122)
mandates AR5 GWP values for ETS compliance reporting.

The tool produces a parallel AR5 output for IANO covering Scope 1 combustion and Scope 1
process emissions. These rows are tagged `regulatory_stream = 'EU_ETS_PHASE_IV'` and
`gwp_set = 'AR5'`. CO2 values are identical between AR6 and AR5 outputs; only the CH4
and N2O CO2e conversion differs (AR6 CH4=27.9 vs AR5 CH4=28; AR6 N2O=273 vs AR5 N2O=265).

The MRR XML submission format is deferred to v2 (see `docs/roadmap.md`). The underlying
tCO2e values are reproducible from this tool's AR5 output.

---

## 12. EU Taxonomy and SFDR Scope

**EU Taxonomy (Regulation 2020/852)**: Alignment assessment (substantial contribution,
do-no-significant-harm, minimum safeguards) is out of scope for v1. The PDF appendix A.7
carries a placeholder disclosure per CG-10: "EU Taxonomy alignment: assessment deferred to v2."

**SFDR PAI indicators**: Not applicable. This is an issuer-level GHG accounting tool; the
reporting entity is not a financial-market participant. No financial-product PAI reporting
is in scope.

---

## 13. Factor Catalog Lifecycle and Publication

This section documents how emission factor records move from draft to published state, the
immutability rule applied to published factors (MG-02), and the separation of duties
between the `data_steward` and `esg_manager` roles. It is required for ESRS 2 BP-2
(methodologies and significant judgements disclosure).

### Draft state

Factor records are created via `POST /api/v1/factor-catalog/` by users holding the
`data_steward` role. A newly created record has `is_published=false`, `published_at=NULL`,
and `published_by=NULL` (the `published_at` / `published_by` columns were split from
`created_at` in migration MG-03, file `alembic/versions/0010_M9_factor_published_at_split.py`,
which resolved an ambiguity where the creation timestamp was being misread as the publication
date). Drafts are fully editable by the `data_steward`: values, units, source references,
and methodology notes may be corrected at any time before publication.

Drafts are **invisible to the calculation engine**. The calc orchestrator filters
`ref.factor_catalog` with `WHERE is_published = true`; draft rows are never selected for
emission calculations.

### Publication workflow

Only the `esg_manager` role may publish a factor. This endpoint is intentionally inaccessible
to `data_steward` (separation of duties — see §13.5 below).

**Endpoint**: `POST /api/v1/factor-catalog/{factor_uuid}/publish`

**Required field — `reason_code`** (controlled enum):

| Code | When to use |
|---|---|
| `INITIAL_PUBLICATION` | First time this `factor_id` / version combination is published |
| `VERSION_BUMP` | Publishing a new version of an existing `factor_id` |
| `METHODOLOGY_UPDATE` | New version reflecting a methodology change (e.g. GWP set upgrade) |
| `SOURCE_REVISION` | New version reflecting an updated source PDF (see ADR-008 for PDF source pinning policy) |
| `CORRECTION_REPLACEMENT` | Publishing a version that supersedes a withdrawn one |

**Optional field — `publish_notes`** (string, max 2000 characters): used to record a
CSRD-grade justification including source PDF title, edition year, and page numbers.
Auditors should expect `publish_notes` to be populated whenever `reason_code` is
`METHODOLOGY_UPDATE` or `SOURCE_REVISION`.

**Pre-conditions checked by the endpoint**:
- Row must exist in the caller's tenant (404 if not found).
- Row must not already be published (409 Conflict if `is_published=true`).
- `is_tbc` must be `false` (422 if the factor is still marked "to be confirmed").
- `value IS NOT NULL OR is_licence_only=true` (422 if neither condition holds).

**On success (all in a single transaction)**:
- `is_published=true`, `published_by` set to the caller's `sub` UUID, `published_at` set to
  `now()` (UTC).
- One row inserted into `calc.audit_log` with `action='factor_published'`, `before_state`
  (the draft snapshot), and `after_state` (the published snapshot including `reason_code`
  and `publish_notes`).

### Immutability rule MG-02

Once `is_published=true`, the database trigger `trg_factor_immutability` fires BEFORE any
UPDATE on `ref.factor_catalog` and raises SQLSTATE P0001 unconditionally. There is no GUC
override path; no application code bypasses this trigger.

Mistakes discovered in a published factor are corrected by creating a **new version** (new
row with a different `version` string) and publishing it with `reason_code =
CORRECTION_REPLACEMENT`. The original row is never modified or deleted. This append-only
pattern mirrors the emissions correction workflow (FR-21 / §5 of this document).

References: MG-02; `alembic/versions/` (migration that installs `trg_factor_immutability`).

### Separation of duties

| Role | Permitted actions | Blocked actions |
|---|---|---|
| `data_steward` | Create drafts; edit drafts; view all draft and published factors | Publish; withdraw |
| `esg_manager` | Publish drafts; view all draft and published factors | Create or edit draft field values (by convention) |
| `auditor` | SELECT on `calc.audit_log`, `ref.factor_catalog` | INSERT / UPDATE / DELETE on any table |

The `published_by` column records the publisher's UUID for every published factor. The
`calc.audit_log` row for `factor_published` additionally records the client IP address and
user-agent string at the time of publication. Together these columns provide a complete
chain of custody from creation to publication.

This role split satisfies ISAE 3000 §A99 (segregation of duties requirement for evidence of
review and authorisation).

### Audit-trail surface

The `calc.audit_log` table is queryable by users with the `auditor` role. Row-Level Security
(M4) grants `auditor` SELECT on all `audit_log` rows within the tenant and blocks
INSERT / UPDATE / DELETE. Auditors should query using:

```sql
SELECT * FROM calc.audit_log
WHERE action = 'factor_published'
  AND (after_state->>'reason_code') = '<code>'
ORDER BY created_at DESC;
```

The `after_state` JSONB column carries the complete published snapshot, including
`reason_code`, `publish_notes`, `published_by`, and `published_at`. Container logs also
emit a structured event named `factor_published` with the same fields. Audits must verify
that both sources (DB row and container log) are consistent; discrepancies must be reported
to the `esg_manager` and escalated to ComplianceAgent.

---

## 14. Methodology Changelog

| Date | Version | Change | Impact |
|---|---|---|---|
| 2026-05-14 | 1.0.0 | Initial publication — incorporates SustainabilityExpertAgent methodology_validation.md v1.0.0 decisions; adds Phase 7/8 security and data-model sections (M7 security-barrier views, SEC-P0-004 refresh role re-fetch, SEC-P0-005 PII hygiene, ADR-007 biogenic column confirmation) | None — first publication; no prior baseline to compare |
| 2026-05-14 | 1.1.0 | Added §13 Factor catalog lifecycle and publication: draft/publish workflow, MG-02 immutability trigger, MG-03 published_at split, separation of duties (data_steward / esg_manager), audit-trail surface. Required for ESRS 2 BP-2. | No change to emission calculations or GWP values. |
