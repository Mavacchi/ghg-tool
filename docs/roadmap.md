# Roadmap — GHG Accounting Tool

**Version**: 1.0.0
**Date**: 2026-05-14
**Status**: APPROVED — documents deferred work from Phase 8 security and reviewer advisories

This document records all items explicitly deferred from v1, with owner agent, target
version, and traceability to the originating finding or advisory. Items are grouped by
urgency and version target. No item in this document represents a defect in v1; each was
deliberately scoped out of the production-ready v1 baseline after explicit review.

---

## v1.1 — Phase 9 Polish (Non-blocking; addressable without production downtime)

These items represent code-quality and maintainability improvements. They do not affect
correctness, security, or regulatory compliance of v1 outputs.

### REV-WAVE3-007 — Celery migration for export_service.py

**Description**: The PDF and Excel export service (`src/ghg_tool/application/services/export_service.py`)
uses an `asyncio.Lock`-guarded in-memory job store to track export jobs. This design is
correct and safe for a single-worker deployment. It breaks at horizontal scale: two API
replicas have independent in-memory stores, so a job submitted to replica A is invisible
to replica B. The v1 deployment profile is single-worker, so this is not a runtime defect.

**Remediation**: Replace the in-memory job store with a Celery task queue backed by Redis
(or equivalent broker). Job state is stored in Redis; any replica can query or cancel any
job.

**Owner**: backend-agent
**Target version**: v1.1
**Finding ID**: REV-WAVE3-007

### REV-WAVE3-010 — Factor source strings hardcoded in Excel summary sheet

**Description**: The Summary sheet of the multi-sheet Excel export
(`src/ghg_tool/ui/excel/sheets.py`) contains hardcoded factor source strings (e.g.
`"DEFRA 2025"`, `"ecoinvent v3.10"`). When the factor catalog version changes, the sheet
strings require a code change. They should be derived from the `factor_source` and
`factor_version` fields of the factor catalog rows used in the corresponding calculation.

**Remediation**: Extract factor source strings to named constants in a shared module, or
derive them directly from the factor catalog data passed to the sheet renderer. Remove all
hardcoded version strings from the Excel template layer.

**Owner**: visualization-agent
**Target version**: v1.1
**Finding ID**: REV-WAVE3-010

### REV-WAVE3-018 — Biogenic memo openpyxl row-juggling refactor

**Description**: The `write_biogenic_memo_sheet` function in the Excel export module uses
manual `openpyxl` row-offset arithmetic to position the biogenic CO2 disclosure memo below
the main data table. The implementation is functionally correct but difficult to maintain:
adding or removing rows above the memo requires updating hard-coded row offsets.

**Remediation**: Refactor to use a named cell range or a structured table reference so that
the memo position is derived from the data extent rather than a fixed offset.

**Owner**: visualization-agent
**Target version**: v1.1
**Finding ID**: REV-WAVE3-018

---

## v2 — Production Hardening (Must be addressed before horizontal scaling or extended public exposure)

These items represent security improvements that are acceptable for v1 single-worker
deployment but must be resolved before horizontal scaling, increased public exposure, or
refresh-token rotation requirements are introduced.

### SEC-P1-004 — Migrate from python-jose to PyJWT (CVE-2024-33664)

**Description**: The current JWT implementation uses `python-jose` 3.3.x, which is
affected by CVE-2024-33664 (algorithm confusion attack: a crafted token can cause
python-jose to accept a symmetric-key token as if it were an asymmetric-key token when
multiple algorithms are simultaneously allowed). The application currently uses HS256 only
with an explicit algorithm allow-list, which mitigates the practical exploit vector. The
advisory is P1 (not P0) because the mitigation is in place.

**Remediation**: Migrate to `PyJWT >= 2.8` with an explicit `algorithms=["HS256"]`
parameter on every `jwt.decode()` call. PyJWT 2.x does not exhibit the algorithm-confusion
vulnerability. Update `pyproject.toml`, `infrastructure/security/jwt.py`, and
`api/routers/auth.py` accordingly. Validate all JWT tests continue to pass after migration.

**Owner**: security-agent + backend-agent
**Target version**: v2
**Finding ID**: SEC-P1-004

### SEC-P1-007 — Refresh token rotation with Redis blacklist

**Description**: In v1, refresh tokens are long-lived (24-hour TTL) and not rotated on
each use. A stolen refresh token remains valid until expiry. There is no server-side
blacklist to invalidate a specific token before its TTL expires (logout is a client-side
no-op in v1).

**Remediation**: Implement per-refresh token rotation:
1. On each `POST /api/v1/auth/refresh`, issue a new refresh token with a fresh `jti`
   (JWT ID) claim and a reduced TTL (1-4 hours recommended).
2. Add the previous refresh token's `jti` to a Redis blacklist with TTL equal to the
   original token's remaining validity.
3. Validate on every refresh that the incoming token's `jti` is not on the blacklist.
4. The logout endpoint becomes a real operation: add the refresh token's `jti` to the
   blacklist immediately on `POST /api/v1/auth/logout`.

This requires a Redis instance in the deployment stack (which is also required for
SEC-ADV-008 rate-limiter migration).

**Owner**: security-agent + backend-agent
**Target version**: v2
**Finding ID**: SEC-P1-007

### SEC-ADV-008 — Redis-backed rate limiter (replace in-process slowapi storage)

**Description**: See `docs/deployment.md` SEC-ADV-008 acknowledged risk. The in-process
rate limiter does not coordinate across replicas.

**Remediation**: Configure slowapi to use a Redis storage backend. The Redis instance
required for SEC-P1-007 (token blacklist) can serve double duty.

**Owner**: backend-agent
**Target version**: v2
**Finding ID**: SEC-ADV-008

---

## v2 — Feature Roadmap

These items represent planned feature additions that are explicitly out of scope for v1.

### EU ETS Phase IV MRR XML upload format

**Description**: The current tool produces AR5 tCO2e values for IANO (Annex I Activity 17)
tagged `regulatory_stream=EU_ETS_PHASE_IV` (FR-34). The MRR XML / verified-report
serialisation format required by the EU ETS registry is **not produced** in v1. The v2
target is to produce a compliant MRR XML submission file from the existing AR5 data.

**Standard reference**: MRR Regulation 2018/2066 as amended by 2023/2122; EU ETS MRR
XML schema published by the European Commission.
**Owner**: backend-agent + compliance-agent
**Target version**: v2
**Finding ID**: FR-34 (deferred scope)

### EU Taxonomy CapEx / OpEx / turnover alignment KPIs

**Description**: EU Taxonomy alignment assessment (substantial contribution criteria,
do-no-significant-harm criteria, minimum social safeguards) is out of scope for v1 per
`docs/requirements.md` §2.2 and CG-10. A placeholder disclosure is present in the PDF
appendix (A.7). v2 to implement the Taxonomy KPI calculation module for NACE C23.31
(manufacture of ceramic tiles and flags).

**Standard reference**: EU Taxonomy Regulation 2020/852; Climate Delegated Act 2021/2139.
**Owner**: sustainability-expert-agent + backend-agent
**Target version**: v2
**Finding ID**: COMP-P1-002 (v2 feature, not a v1 defect)

### SFDR PAI indicators

**Description**: SFDR Principal Adverse Impact indicators are not applicable to v1 (the
reporting entity is not a financial-market participant). If scope expands to include
investor-facing reporting (e.g. if the company is acquired by or reports into a financial
group), SFDR PAI indicators (Annex I, Table 1-3) must be added.

**Standard reference**: SFDR Regulation 2019/2088; RTS Commission Delegated Regulation
2022/1288.
**Owner**: sustainability-expert-agent
**Target version**: v2 (if scope change confirmed)
**Finding ID**: requirements.md §4 (out of scope v1)

### GHG Protocol Scope 3 Hot Spot Analysis

**Description**: v1 implements the 9 material Scope 3 categories. A Hot Spot Analysis per
GHG Protocol Corporate Value Chain Standard Chapter 7 would identify which Scope 3 sub-
categories within Cat 1 (purchased goods) contribute disproportionately to the total and
guide supplier engagement priorities. This requires spend-data enrichment and supplier-
specific emission factor collection.

**Standard reference**: GHG Protocol Corporate Value Chain (Scope 3) Standard (2011), Ch. 7.
**Owner**: sustainability-expert-agent + data-analyst-agent
**Target version**: v2
**Finding ID**: OI-5 (Phase 2, partially addressed; hot spot ranking deferred)

### Multi-tenant management UI

**Description**: The database schema supports multi-tenancy via the `tenant_id` column
and RLS policies (M4 migration). v1 is single-tenant (one row in `ref.tenants`). v2 to
add an admin panel for tenant onboarding: creating tenants, assigning users, and
initialising per-tenant factor catalogs.

**Owner**: backend-agent + visualization-agent
**Target version**: v2
**Finding ID**: requirements.md §2.2 (single-tenant v1 design choice)
