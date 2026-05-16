# Roadmap — GHG Accounting Tool

**Version**: 2.0.0
**Date**: 2026-05-16 (post wave-5)
**Status**: APPROVED — supersedes v1.0.0 (2026-05-14, pre-wave-3)

This document records work explicitly deferred from the current production
baseline, with owner agent, target wave/version, and traceability to the
originating finding or advisory.

For features and findings that have **already shipped**, see
[`CHANGELOG.md`](../CHANGELOG.md). For per-finding audit-trail records (BLOCK
/ REQUIRED / INFO severity with status), see [`audit-trail.md`](audit-trail.md).

---

## Wave 6 — Quality Follow-up (next planned wave)

These items were explicitly deferred during wave 5 with ticket-quality
rationale. None blocks production deployment of the current baseline.

### REQ-import-linter-violations

**Description**: Wave 5 wired `import-linter` into CI with hexagonal
contracts (`domain` → no deps; `application` → only `domain`; etc.). 9
pre-existing violations were documented and the CI step runs in *warning
mode* (`continue-on-error: true`).

**Remediation**: Resolve the 9 violations (mostly `application` → `api` /
`ui` reverse-imports and `infrastructure` → `application` reverse-imports).
Drop `continue-on-error`.

**Owner**: refactor-agent + architect-agent
**Target**: wave 6
**Finding ID**: REQ-import-linter (audit-trail.md wave 5)

### REQ-cve-transitive-major-upgrade

**Description**: `pip-audit` reports 10 CVE in transitive dependencies
(starlette, streamlit, weasyprint, pillow). These require a major version
upgrade of FastAPI and Streamlit. CI ignores them with explicit
`--ignore-vuln` flags.

**Remediation**: Upgrade FastAPI 0.111 → 0.115+ and Streamlit 1.35 → 1.40+;
regenerate the lock file; re-run the full test suite; remove
`--ignore-vuln` flags.

**Owner**: security-agent + devops-agent
**Target**: wave 6
**Finding ID**: REQ-cve-transitive (audit-trail.md wave 5)

### REQ-mypy-ignore-errors-cleanup

**Description**: `pyproject.toml` contains 18 module-level
`ignore_errors = true` overrides for mypy. Root causes were analysed:
SQLAlchemy 2.0 `rowcount` typing gap (CursorResult vs Result),
Streamlit `T | None` returns, pandas-stubs incompleteness, and a few
legacy `Any`-heavy modules.

**Remediation**: Per-module fix plan available; tackle one module at a
time, removing the `ignore_errors` after each.

**Owner**: refactor-agent + python-expert-agent
**Target**: wave 6
**Finding ID**: REQ-mypy-ignore-errors (audit-trail.md wave 5)

### REQ-auth-router-refactor

**Description**: `api/routers/auth.py::login` (179 LOC) and `refresh`
(195 LOC) exceed the 50-LOC reviewer guideline. Functions are tightly
coupled to DB session + TOTP + session-rotation logic.

**Remediation**: Gated on integration-test coverage being added first;
once safe, decompose into a service layer (`AuthLoginService`,
`AuthRefreshService`) mirroring the `FactorPublishService` extraction
pattern from wave 5.

**Owner**: refactor-agent
**Target**: wave 6
**Finding ID**: REQ-auth-router-refactor (audit-trail.md wave 5)

### REQ-e2e-full-pipeline

**Description**: `tests/integration/e2e/test_full_pipeline.py` scaffold
exists (4 methods) but is `pytest.skip`'d because it needs a live PG
instance + Celery-eager fixture coordination.

**Remediation**: Build the shared fixture, enable the tests, and gate
the deployment workflow on E2E success.

**Owner**: test-agent + devops-agent
**Target**: wave 6
**Finding ID**: REQ-e2e-pipeline (audit-trail.md wave 5)

### REQ-arch-doc-role-rename

**Description**: `docs/architecture.md` still uses the pre-wave-3 role
names (`data_steward / esg_manager / auditor`) throughout its narrative,
Mermaid diagrams, and SQL examples. A banner has been added documenting
the 1:1 mapping, but the document itself was not rewritten.

**Remediation**: Full document rewrite — replace role names in all
narrative sections, regenerate Mermaid diagrams, update RBAC tables and
SQL `SET LOCAL` examples.

**Owner**: documentation-agent + architect-agent
**Target**: wave 6
**Finding ID**: post-wave-5 documentation cleanup

---

## Open Questions — Outstanding (no target wave yet)

These items are normative/policy decisions that need stakeholder input
before they can be assigned to a wave.

### ISPRA factor: production-side vs consumption-side

The Italian grid factor is currently pinned at **0.216 kgCO2/kWh** (production-side,
ISPRA 2024). GHG Protocol Scope 2 §4.2 recommends a **consumption-side**
factor (~0.243 kgCO2/kWh after import-mix and grid-loss adjustments). The
current pin is an interim measure.

**Remediation**: Extract ISPRA 2024 Table 3 (consumption-side); migration
to repin.

**Owner**: sustainability-expert-agent
**Target**: TBD
**Tracking**: `docs/factor_sources.md` §O1

### Privacy notice placeholders

The GDPR Art. 13 privacy notice rendered on the Login + Admin pages
contains placeholder `[Titolare]` and `[DPO]` strings. Deployment-time
configuration via env vars `GHG_CONTROLLER_NAME` and `GHG_DPO_EMAIL` is
documented but not enforced.

**Remediation**: Either enforce non-empty values at startup, or replace
the placeholders with a configurable Markdown block read from `docs/`
at render time.

**Owner**: compliance-agent + backend-agent
**Target**: TBD

---

## Future / v2 — Feature Roadmap

These items are explicitly out of scope for v1 (the current production
baseline) and represent multi-wave feature additions.

### EU ETS Phase IV MRR XML export format

**Description**: The current tool produces AR5 tCO2e values for IANO
(Annex I Activity 17) tagged `regulatory_stream=EU_ETS_PHASE_IV` (FR-34).
The MRR XML / verified-report serialisation format required by the EU ETS
registry is **not produced** in v1.

**Remediation**: Implement an MRR XML exporter that serialises the existing
AR5 data into the EU ETS registry schema.

**Standard reference**: MRR Regulation 2018/2066 as amended by 2023/2122;
EU ETS MRR XML schema published by the European Commission.

**Owner**: backend-agent + compliance-agent
**Target**: v2
**Finding ID**: FR-34 (deferred scope)

### EU Taxonomy CapEx / OpEx / turnover alignment KPIs

**Description**: EU Taxonomy alignment assessment (Substantial Contribution
criteria, Do-No-Significant-Harm criteria, minimum social safeguards) is
out of scope for v1 per `docs/requirements.md` §2.2 and CG-10. A placeholder
disclosure is present in the PDF appendix (A.7).

**Remediation**: Implement the Taxonomy KPI calculation module for
NACE C23.31 (manufacture of ceramic tiles and flags).

**Standard reference**: EU Taxonomy Regulation 2020/852; Climate Delegated
Act 2021/2139.

**Owner**: sustainability-expert-agent + backend-agent
**Target**: v2
**Finding ID**: COMP-P1-002 (v2 feature, not a v1 defect)

### SFDR PAI indicators

**Description**: SFDR Principal Adverse Impact indicators are not applicable
to v1 (the reporting entity is not a financial-market participant). If scope
expands to include investor-facing reporting (e.g. if the company is acquired
by or reports into a financial group), SFDR PAI indicators (Annex I, Tables
1–3) must be added.

**Standard reference**: SFDR Regulation 2019/2088; RTS Commission Delegated
Regulation 2022/1288.

**Owner**: sustainability-expert-agent
**Target**: v2 (if scope change confirmed)
**Finding ID**: requirements.md §4 (out of scope v1)

---

## Completed — Already Shipped

The following items previously appeared in this roadmap and have since
shipped. They are listed here for traceability; full detail is in
[`CHANGELOG.md`](../CHANGELOG.md).

### Wave 4 (PR #45, 2026-05-16)

- ✅ **REV-WAVE3-007** — Celery migration for export_service (replaced in-memory
  `asyncio.Lock` store with Celery + Redis broker)
- ✅ **REV-WAVE3-010** — Dynamic factor source labels in Excel summary sheet
  (no more hardcoded "DEFRA 2025" / "ecoinvent v3.10" strings)
- ✅ **SEC-P1-004** — PyJWT migration from python-jose (CVE-2024-33664 mitigated
  fully, not just by allow-list)
- ✅ **SEC-P1-007** — Refresh-token rotation with Redis-backed JWT blacklist
- ✅ **SEC-ADV-008** — Redis-backed rate limiter (multi-instance coordinated)
- ✅ **GHG Protocol Scope 3 Hot Spot Analysis** — service + endpoint + UI page
- ✅ **Multi-tenant management UI** — admin panel for tenant onboarding,
  user assignment, per-tenant factor catalogs
- ✅ **NCV dual-unit factor variants** (migration `0028_M8`)
- ✅ **JWT lazy user provisioning** for SSO-origin tokens
- ✅ **Real seed_loader pipeline** — DEFRA / ISPRA / AIB / Ecoinvent ingestion
  (replaces the v1 stub)

### Wave 5 (PR #46, 2026-05-16)

- ✅ **REV-WAVE3-018** — Biogenic memo openpyxl refactor was superseded by
  REV-WAVE3-010 (factor sources now derive from catalog data; memo position
  follows). Closed without separate work.
- ✅ **GDPR Art. 13 privacy notice** on Login + Admin pages
- ✅ **GDPR Art. 17 erasure endpoint** — `DELETE /api/v1/users/{id}` with
  pseudonymisation + audit_log (migration `0032_M12` adds `users.erased_at`)
- ✅ **audit_log 10-year retention** via pg_cron archive job (migration
  `0029_M9`) — CSRD audit-trail durability requirement
- ✅ **Schema hardening** (migration `0030_M10`): `ref.tenants` RLS, GIST
  temporal exclusion constraints, partial index `is_published`, `search_path`
  injection fix in 2 SECURITY DEFINER functions
- ✅ **Factor pinning** (migration `0031_M11`): ISPRA 0.216 (interim), AIB
  0.441, 4 DEFRA WTT factors
- ✅ **`docs/factor_sources.md`** — 40 `factor_id` documented with source URL,
  publication date, retrieval date
- ✅ **JWT blacklist fail-closed** when Redis unreachable (was fail-open)
- ✅ **`SQLALCHEMY_URL` fail-closed** at module import (no insecure default)
- ✅ **SQL injection fixes** in migrations 0028 + 0003 (parametrised via
  `sa.text().bindparams()`)
- ✅ **XSS escapes** in 13 Streamlit `unsafe_allow_html` blocks
- ✅ Filename collision fix: `0012_M13` → `0013b_M13`
- ✅ `0005_M4` downgrade: restrict `password_hash` GRANT to app role
  (not `PUBLIC`)
- ✅ Coverage 87.05% → 93.25% (calc/* + domain/* at 100%)

### Wave 3 (PRs #33–#44, 2026-05-15)

- ✅ **Role rename** `data_steward / esg_manager / auditor` →
  `editor / admin / viewer` (1:1 mapping, internal migration tag M24)
- ✅ **Auto-calc** flow (consumption → tCO2e preview → idempotent insert)
- ✅ **Excel template** generator (`GET /api/v1/raw/excel/template`)
- ✅ **Site-type filter** + country-aware LB factor lookup
- ✅ **Idempotency-Key** on `POST /calc/insert`
- ✅ **Factor-catalog CRUD** + **emission correction** workflow
- ✅ **Bootstrap admin** from env (`GHG_BOOTSTRAP_ADMIN_*`)
- ✅ Demo mode hardening + production-safe defaults

---

## Document control

- This document is updated at the close of each wave by the orchestrator-agent.
- Items move from `Wave N — planned` → `Completed` as they ship; the
  CHANGELOG entry is created in the same PR.
- New items entering this document require a Finding ID (either a wave-level
  REQUIRED, a deferred BLOCK with rationale, or a stakeholder-raised feature
  request).
