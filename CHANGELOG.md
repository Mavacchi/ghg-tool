# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows wave-based delivery (no semver releases yet — see the
`[Unreleased]` and `[Wave-N]` sections below).

For finer-grained audit detail (BLOCK / REQUIRED / INFO findings, owning agent,
remediation commits, deferred items with rationale) see [`docs/audit-trail.md`](docs/audit-trail.md).

---

## [Unreleased] — wave-6 backlog

### Deferred from wave 5 (with explicit TODO + ticket-quality rationale)

- **Import-linter:** 9 hexagonal-contract violations (`application` → `api`/`ui`,
  `infrastructure` → `application`). CI step enabled in *warning mode* via
  `continue-on-error: true`; full remediation requires an architectural refactor
  cluster.
- **CVE in transitive deps (×10):** starlette, streamlit, weasyprint, pillow.
  Require major upgrade of FastAPI / Streamlit. Documented in CI with explicit
  `pip-audit --ignore-vuln` flags + ticket reference.
- **mypy `ignore_errors=true` overrides (×18):** SQLAlchemy 2.0 `rowcount` typing
  gap, Streamlit `T | None` returns, pandas-stubs. Analysis complete; per-module
  fix plan documented.
- **Auth router refactor:** `login` (179 LOC) + `refresh` (195 LOC) deliberately
  left at current size — tightly coupled to DB + TOTP + session rotation; safe
  refactor needs integration-test coverage first.
- **E2E full-pipeline test:** scaffold present (`tests/integration/e2e/test_full_pipeline.py`),
  currently skipped — requires live PostgreSQL + Celery-eager fixture coordination.

### Outstanding open questions

- **ISPRA factor:** pinned at 0.216 (production-side) as interim. GHG Protocol
  Scope 2 §4.2 requires consumption-side (~0.243). Follow-up migration needs
  PDF Table 3 extraction. Tracked in [`docs/factor_sources.md`](docs/factor_sources.md) §O1.
- **Privacy notice text:** placeholder `[Titolare]` requires per-deployment
  configuration via `GHG_DPO_EMAIL` / `GHG_CONTROLLER_NAME` env vars.

---

## [Wave-5] — 2026-05-16

**Theme: Quality remediation.** Full audit-team report (7 specialized agents:
Security / Compliance / Sustainability / Reviewer / Test / Architect /
DataEngineer) translated into 9 parallel remediation clusters.

**PR:** [#46](https://github.com/Mavacchi/ghg-tool/pull/46) · 31 commits ·
**13/13 BLOCK + 45/50 REQUIRED resolved** · coverage 87.05% → **93.25%** ·
Alembic chain 28 → **32 migrations** (linear, head `0032_M12`).

### Security

- **BLOCK-1 / BLOCK-2 / BLOCK-6:** parametrise migration `INSERT`s with
  `sa.text().bindparams()` (SQL injection fix in migrations 0028 + 0003);
  raw-table allow-list in `api/main.py`; demo seeding gated to exclude staging.
- **BLOCK-3 (CWE-79):** escape DB-sourced data in 13 Streamlit
  `unsafe_allow_html` blocks.
- **BLOCK-4 / BLOCK-5 / BLOCK-7:** remove insecure default for `SQLALCHEMY_URL`
  (fail-closed at module import); JWT blacklist becomes **fail-closed** when
  Redis is unreachable; demo-mode token rejected server-side (not just on UI).
- `python-multipart>=0.0.27` to mitigate CVE-2024-24762 + 3 follow-up CVEs.
- Compose `*_FILE` secrets enforced via `:?required` shell syntax.

### Database

- Migration `0029_M9`: `audit_log` 10-year retention via `pg_cron` archive job
  (AL-A finding).
- Migration `0030_M10`: schema hardening — `ref.tenants` RLS, GIST temporal
  exclusion constraints, partial index `is_published`, `search_path` injection
  fix (RLS-A / M1-A / BT-A / IDX-A).
- Migration `0031_M11`: pin ISPRA 0.216, AIB 0.441, 4 DEFRA WTT factors
  (verified via WebSearch + WebFetch on official sources).
- Migration `0032_M12`: GDPR `users.erased_at` column for Art. 17 erasure.
- Rename `0012_M13_report_snapshots.py` → `0013b_M13_*` (MQ-A: filename
  collision with `0013_M13`).
- Fix `0005_M4` downgrade `GRANT` on `password_hash` (SCH-A: was granted to
  `PUBLIC`, now restricted to app role).

### GDPR / Compliance

- `feat(gdpr)`: privacy notice (Art. 13 GDPR) rendered on Login + Admin pages
  via `render_privacy_notice` helper (F-14).
- `feat(gdpr)`: admin endpoint `DELETE /api/v1/users/{id}` performs
  pseudonymisation + writes to `audit_log` (Art. 17, F-15).

### Methodology / Sustainability

- New `docs/factor_sources.md` (335 lines, 40 `factor_id` documented with
  source URL, publication date, retrieval date, and methodology notes).
- ISPRA / AIB / WTT values pinned in migration 0031_M11 (interim — see open
  questions above for ISPRA consumption-side).

### Refactor

- Extract `FactorPublishService` from `factor_catalog.py` router (1271 → 1033 LOC).
- Decompose `_preview_s3_cat12` (468 LOC, finding #1) into 4 helper functions.
- Type strengthening: `session: Any` → `AsyncSession` across the codebase.
- DRY HTTP helper: `_http_client.safe_request` deduplicates 6 UI clients.
- Typed exception handling: `IntegrityError + UniqueViolation` instead of
  string-matching on error messages (`handle_unique_violation()` context manager).
- Magic numbers in `celery_app.py` → `Final` constants.
- Decompose `import_excel` router handler into 4 private helpers.
- `print()` → structured logger.
- SHA256 guards added to `seed_loader`.

### Tests

- 4 flaky JWT-related tests resolved via autouse `_reset_jwt_module_state`
  fixture (verified across 3 consecutive runs).
- New unit coverage: `calc_scheduler` 40 → **100%**, `export_tasks` 28 → **100%**,
  `sbti_target` 81 → **100%**, `brand` / `filters` / `help` 0 → **100%**.
- New integration coverage: `recalc_gwp_switch` (17 tests); E2E pipeline
  scaffold (4 methods skipped pending live-PG fixture).
- Edge cases: `scope2_lb` missing-grid, `scope3_cat3` missing-WTT, AR4
  rejection (property-based).
- `apscheduler` happy-path tests gated by `importlib.util.find_spec` (package
  is an optional dependency).

### CI / DevOps

- `pip-audit` step added to the security workflow (6 CVE resolved by upgrades;
  10 deferred — see Unreleased).
- `import-linter` wired with hexagonal contracts in warning mode (9 violations
  documented).
- `mypy ignore_errors=true` debt fully analysed (18 module overrides; per-module
  fix plan available).

### Fixed (CI follow-ups during PR #46)

- Lint: 42 ruff errors (39 auto-fixed + 7 manual B904 `raise ... from exc`).
- `tests/integration/postgres/test_migration_0027.py` assertions widened from
  hardcoded `{0027_M7, 0028_M8}` to `numeric_prefix >= 27`.
- mypy: `Result[Any].rowcount` (SQLAlchemy 2.0 typing), `FactorPublishService`
  forward-ref via `TYPE_CHECKING`, `CurrentUser` → `_UserContext` Protocol
  mismatch.
- `infrastructure/db/session.py`: pytest detection via `"pytest" in sys.modules`
  (the previous `PYTEST_CURRENT_TEST` guard didn't fire during *collection*).
- `tests/unit/application/test_export_tasks.py`: assert against
  `PDFBuildError` / `XlsxBuildError` wrappers + `__cause__`, not the
  underlying `RuntimeError` / `ValueError`.

---

## [Wave-4] — 2026-05-16

**Theme: Mega — security v2 + Celery + Hot Spot + multi-tenant + NCV +
Scope-3 corporate decoupling + seed-loader.**

**PR:** [#45](https://github.com/Mavacchi/ghg-tool/pull/45) · 29 commits.

### Security v2

- **SEC-P1-004:** migrate `python-jose` → `PyJWT` (CVE-2024-33664 mitigation).
- **SEC-P1-007:** refresh-token rotation + Redis-backed JWT blacklist.
- **SEC-ADV-008:** Redis-backed rate limiter (multi-instance coordination).

### Added

- Migration `0027_M7`: wave-4 foundation — `pg_cron` extension +
  `cache.idempotency_keys` cleanup job.
- Migration `0028_M8`: NCV dual-unit factor variants for DEFRA 2024 (Net
  Calorific Value: distinct rows for energy-content vs mass/volume basis).
- Real seed_loader pipeline: replaces stub with DEFRA / ISPRA / AIB / Ecoinvent
  ingestion.
- **JWT lazy user provisioning** for SSO-origin tokens (Task B).
- **Scope-3 corporate decoupling:** `codice_sito` can now be NULL for Scope 3
  emissions (Task A — corporate-level reporting where site attribution doesn't
  apply).
- **Hot-spot analysis** service + `POST /api/v1/hotspots/analyze` endpoint
  (Task C).
- **Hot Spot UI page** + `hotspot_client` + unit tests.
- **Tenant Management** router + UI page + tests (Task 4: admin can list /
  create / update tenants).
- **WTT replica button** on Data Entry page (Task 2).
- **Export pipeline migrated to Celery** background queue (REV-WAVE3-007).
- **Polling export adapter** + Reports page integration (Task 6).

### Changed

- `excel/sheets.py`: dynamic factor-source labels (REV-WAVE3-010).
- Alembic chain re-linearised after parallel branches.

### Fixed

- `0028` downgrade: temporarily `DISABLE TRIGGER` to bypass CSRD anti-mutation
  guard during reversibility test only.
- `0027` migration: nested dollar-quote tagging, `op.get_bind().exec_driver_sql()`
  to bypass SQLAlchemy pyformat compiler interpretation of `%` in `RAISE NOTICE`.
- Unxfail `TestSecP1005LoginWired 401/200` (proper session mock).
- Unxfail migration-chain tests (env-precedence + `alembic_version` reset).

---

## [Wave-3] — 2026-05-15 (Ondata 1 + 2 + 3 + bugfix)

**Theme: UX polish, CRUD autonomo, role rename, Excel auto-calc, open-questions
closure.**

**PRs:** #33 through #44 (12 PRs).

### Added (Ondata 3 — PR #43)

- Migration `0026_M6`: `site_type` + `country` + `raw.direct_entry` +
  `idempotency_keys` (closes 9 open questions from `auto_calc_design.md`).
- `GET /api/v1/sites` exposes `site_type` + `country`.
- Site-type filter in auto-calc form (UI decision #7).
- `country`-aware location-based factor lookup (LB).
- Idempotency-Key header on `POST /calc/insert` (decision #6).
- Raw `direct_entry` persistence + `raw_row_id` link (FR-22).

### Added (Ondata 2 — PR #42)

- `auto_calc_service` with 12 per-scope sub-handlers
  (consumption → tCO2e auto-conversion).
- `POST /calc/preview` + `POST /calc/insert` endpoints.
- Auto-calc tab on Data Entry page (form + preview + insert flow).
- `GET /api/v1/raw/excel/template` returns prefilled workbook ("Scarica modello
  Excel" button).
- `docs/methodology/auto_calc_design.md` — normative decisions for the auto-calc
  pipeline.

### Added (Wave bugfix + UX — PRs #33–#41)

- **CRUD autonomo:** factor catalog edit/delete affordances; emission correction
  workflow (`POST /emissions/{id}/correct` append-only via `superseded_by`).
- **Role rename:** `data_steward` / `esg_manager` / `auditor` →
  **`admin` / `editor` / `viewer`** (microcopy + mobile-responsive layout).
- **Bootstrap admin** from env on startup (`GHG_BOOTSTRAP_ADMIN_*`, idempotent).
- **Demo mode** auto-on for development; production-safe defaults
  (`GHG_DEMO_ALLOWED_ENVS`).
- **Config:** `GHG_DASHBOARD_ID` (was hardcoded `esg-main-2026`),
  `GHG_API_BASE_URL` in UI (fixes silent docker login).
- Excel/PDF export round-trip with completion-state UI.
- Dynamic factor sources in footers and PDF (no hardcoded "ISPRA / IEA").
- Auto-bootstrap `.env` + propagate `GHG_JWT_SECRET` into container.
- `scripts/create_admin.py` + `create-admin.bat` for first-admin bootstrap.

### Changed

- 16 new i18n keys (it/en) — destructive-button + success-toast classes.
- `/correct` RBAC aligned (editor + admin only).
- Legacy bulk-correction expander removed.

---

## [Wave-2] — 2026-05-15

**Theme: Test debt cleanup.**

**PR:** [#32](https://github.com/Mavacchi/ghg-tool/pull/32).

### Fixed

- Unxfail 12 pre-existing skipped tests: RLS / SEC fixture / two-eyes / M0
  baseline.

---

## [Wave-1] — 2026-05-15

**Theme: Q1.A foundation.**

**PR:** [#31](https://github.com/Mavacchi/ghg-tool/pull/31).

### Added

- Auth validation (JWT login wiring, refresh, RBAC).
- `dual_run_id` infrastructure (parallel computation of AR4 vs AR5/AR6 for
  recalculation transparency).

### Changed

- GHG calculation pipeline migrated to `Decimal` (replaces `float`) — eliminates
  IEEE-754 rounding drift on consolidated tCO2e totals.

---

## [Bootstrap] — 2026-05-14

**PR:** [#3](https://github.com/Mavacchi/ghg-tool/pull/3).

### Fixed

- 12 bugs identified during initial cross-cutting code review.

---

## Notes for maintainers

- Wave numbering reflects internal delivery cadence, not semver. When the
  project adopts semantic versioning, this file will be re-keyed.
- Date format: `YYYY-MM-DD` (Europe/Rome timezone, matches commit `%ai`).
- "Audit-trail" tagging convention: BLOCK = blocking severity (security /
  compliance gates), REQUIRED = must-fix before merge (non-blocking),
  INFO = advisory. See `docs/audit-trail.md` for the per-finding table.
