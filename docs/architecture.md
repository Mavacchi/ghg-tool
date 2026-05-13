# Architecture Design — GHG Accounting Tool (Phase 4)

Ceramic-Tile Manufacturer (gres porcellanato) — 7 Italian Production Sites
Base Year 2024 — Operational Control — CSRD ESRS E1 — ISAE 3000 Limited — EU ETS Phase IV (IANO Annex I Activity 17, OI-7 closed YES)

---

## 0. Document Control

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Date | 2026-05-13 |
| Author | architect-agent |
| Status | ISSUED — Phase 4 output, ready for Phase 5 (data-engineer + backend + visualization) handover |
| References (input) | `docs/requirements.md` v1.2.1 (APPROVED); `docs/methodology_validation.md` v1.0.0; `docs/data_quality_report.md` v1.0.0 |
| Scope of this document | Regulatory-grade architecture for v1: layered design, persistence model, ETL pipeline, RBAC/RLS, observability, deployment, gate-mapping. No production code is written — DDL and configuration excerpts embedded as design artefacts only. |
| Tech stack (locked) | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x + Alembic, pandas (primary) / polars (deferred — see ADR-001), pandera, pytest + hypothesis, structlog, python-jose, bcrypt, WeasyPrint, openpyxl, Streamlit, Plotly, PostgreSQL 15, Docker Compose, GitHub Actions. |
| Out of scope | Production-code authoring (delegated to Phase 5); regulatory MRR XML serialisation (out of v1, only AR5 tCO2e reproducibility required); multi-tenant orchestration; mobile UI; SBTi pathway (OI-1). |

### 0.1 Document Decision Log (high-level — section-level decisions captured inline)

| ID | Decision | Alternatives Considered | Rationale | Refs |
|---|---|---|---|---|
| AD-001 | Hexagonal / ports-and-adapters layering with `domain/` independent of frameworks | Layered MVC; clean architecture (full); transaction script | Calc modules must be 100% unit-testable per NFR-15; immutability invariants are domain rules not infra; supports future swap of FastAPI → other transport without rewriting calc | NFR-15, NFR-21, FR-20 |
| AD-002 | Append-only `emissions_consolidated` with bitemporal `valid_from`/`valid_to`/`superseded_by` + `deny_update_delete` trigger | Audit-table mirror; event sourcing full | FR-20 explicitly mandates DB-enforced immutability; CG-03 requires CI-tested trigger; bitemporal supports point-in-time auditor queries | FR-20, FR-21, NFR-14, NFR-21, CG-03, CG-04 |
| AD-003 | Factor catalog immutable post-publish with `(factor_id, version, gwp_set)` natural key; `valid_from`/`valid_to` for vintage | Mutable factor table; separate versioning service | MG-01/02 require immutability; OI-5 requires version pinning; auditor must reproduce historical calcs exactly | MG-01, MG-02, FR-04, NFR-19 |
| AD-004 | AR5 dual-track implemented as parametrised single ETL run with dual-write (gwp_set tag), not separate pipeline | Separate AR5 pipeline; runtime GWP swap | OI-7 confirmed YES; MG-12 mandatory; activity data is identical between AR6 and AR5 (only GWP table differs); dual-write avoids reconciliation between runs | FR-19, FR-34, MG-10, MG-12 |
| AD-005 | Pandas as primary ETL dataframe library for v1; polars deferred | polars first; dask | NFR-01 budget is < 10 min on tiny dataset (32+16+101 raw rows); pandera integrates natively with pandas; polars adoption reassessed if Phase 5 perf testing breaches 10 min — see ADR-001 seed | NFR-01 |
| AD-006 | WeasyPrint (HTML/CSS → PDF) over ReportLab | ReportLab; pdfkit; LaTeX | CSRD ESRS E1-6 tables align naturally to HTML; designers can iterate on CSS without Python changes; supports Italian/English locale via simple template swap | FR-28, FR-33, CG-06, CG-07 |
| AD-007 | Single-tenant v1 with `tenant_id` column on every row defaulted to canonical tenant UUID | True multi-tenant from day 1; schema-per-tenant only | §14 "out of scope: multi-tenancy"; but SG-03 mandates the design must accommodate future multi-tenant RLS row isolation; columnar approach keeps v1 simple while preserving the option | SG-03, NFR-06, requirements.md §14 |
| AD-008 | PostgreSQL Row-Level Security (RLS) as defence-in-depth alongside FastAPI middleware | API-only RBAC; OPA / Casbin sidecar | SG-02 / SG-03 mandate defence-in-depth at DB and app layers; RLS native to PostgreSQL, no extra component to operate; auditor read-only enforcement at DB is provable in ISAE 3000 evidence | SG-02, SG-03, NFR-06, FR-31 |
| AD-009 | Alembic migrations versioned by Phase 5 sub-deliverable (M0..M5) | Sequential numeric only | Auditor traceability: each Phase 5 sub-deliverable maps to a single migration; rollback / replay deterministic | FR-04, FR-20, FR-22 |
| AD-010 | DLQ as a typed table `dlq` with `parent_finding_id` lineage to `dq_findings`; both append-only | DLQ as file system / Kafka queue | data_quality_report §13.1; preserves single-DB transactional integrity; auditor can join DLQ ↔ findings ↔ raw ingestions | data_quality_report §13.1/13.2, NFR-13, FR-32 |

---

## 1. System Context (C4 Level 1)

The tool is operated by three internal RBAC roles (data_steward, esg_manager, auditor) and consulted by two external read-only audiences (ISAE 3000 assurance provider, EU ETS verifier). Input is annual batch CSVs; output is dashboard views, Excel exports, CSRD-aligned PDF reports, and an FastAPI REST interface for future ERP/CRM integration (Phase 5+).

```mermaid
graph TB
    DS["data_steward<br/>(ingest, factor catalog,<br/>GO QC checklist)"]
    EM["esg_manager<br/>(approve, export,<br/>waiver findings)"]
    AU["auditor<br/>(read-only audit trail)"]
    ISAE["External assurance<br/>(ISAE 3000 Limited)"]
    ETS["EU ETS verifier<br/>(IANO AR5 stream)"]

    RAW[("/data/raw/*.csv<br/>scope1, scope2, scope3<br/>UTF-8 BOM, ; delim")]
    ERP["(Phase 5+ deferred)<br/>ERP/CRM/MES<br/>via FastAPI POST"]
    GO["GO certificate PDFs<br/>(GSE issuance docs)"]

    subgraph SYS["GHG Accounting Tool (v1)"]
        APP["Streamlit dashboard +<br/>FastAPI API +<br/>ETL runner +<br/>PostgreSQL"]
    end

    OUT_PDF["CSRD PDF<br/>(ESRS E1-6, AR6)"]
    OUT_XLS["Excel multi-sheet<br/>(audit trail, factor snapshot)"]
    OUT_API["JSON API<br/>(read + append)"]
    OUT_DASH["Streamlit dashboard<br/>(drill-down, YoY,<br/>intensity, DQ, audit)"]
    OUT_AR5["AR5 data stream<br/>(EU ETS reproducibility,<br/>same correlation_id)"]

    DS -->|login, ingest, populate QC, register factor| SYS
    EM -->|login, approve PDF, trigger export, waiver| SYS
    AU -->|login (read-only), browse audit trail| SYS
    RAW -->|annual batch| SYS
    GO -->|PDF upload + QC1..QC8| SYS
    ERP -.->|future POST /emissions| SYS

    SYS --> OUT_PDF
    SYS --> OUT_XLS
    SYS --> OUT_API
    SYS --> OUT_DASH
    SYS --> OUT_AR5

    OUT_PDF --> ISAE
    OUT_XLS --> ISAE
    OUT_DASH --> ISAE
    OUT_AR5 --> ETS
```

External-system boundary notes:
- **Raw CSVs** are immutable from the tool's perspective: per requirements.md §10 and resolution-addendum §14, the native CSV files in `/data/raw/` are never modified — all DQ remediations (FR-01 VIANO_GARGOLA zero, FR-02 SASSUOLO Grid zero, FR-37 Cat 3 metadata defaulting) are deterministic ETL transforms.
- **EU ETS authority** is a **downstream consumer of AR5 tCO2e values**, not an interactive party; the MRR XML / verified-report format is explicitly out of v1 scope (requirements.md §14, FR-34). The architecture only guarantees that AR5 tCO2e values from this tool are reproducible against the source data and factor catalog.
- **GO certificate PDFs** are stored in object storage (Docker-volume in v1; MinIO/S3-compatible interface for future).
- **ERP/CRM integration** (FR-29, FR-30) is `SHOULD` priority — endpoints exposed in v1 with JWT/RBAC, but no live consumer in v1.

---

## 2. Container Diagram (C4 Level 2)

```mermaid
graph TB
    subgraph CLIENT["Browser clients"]
        DASH_C["Streamlit UI<br/>(data_steward / esg_manager / auditor)"]
        OAS["OpenAPI Swagger UI<br/>(API consumers)"]
    end

    subgraph COMPOSE["Docker Compose stack"]
        ST["streamlit_app<br/>(Streamlit 1.x + Plotly)<br/>port 8501"]
        API["fastapi_app<br/>(FastAPI + Pydantic v2 +<br/>SQLAlchemy 2.x async)<br/>port 8000"]
        ETL["etl_runner<br/>(Python script, cron-triggered<br/>or on-demand)"]
        DB[("postgres-15<br/>schemas: raw, ref, calc,<br/>audit, ops")]
        OBJ[("minio<br/>S3-compatible<br/>(GO PDFs)")]
        RED[("redis (optional)<br/>(rate-limit + cache)")]
    end

    subgraph CI["GitHub Actions"]
        CI1["lint (ruff, mypy --strict)"]
        CI2["test (pytest + coverage 85/100)"]
        CI3["security (gitleaks, bandit)"]
        CI4["build + push images"]
    end

    DASH_C -->|HTTPS| ST
    OAS -->|HTTPS| API
    ST -->|REST/JSON + JWT| API
    API --> DB
    API --> OBJ
    API -->|rate-limit, cache| RED
    ETL --> DB
    ETL --> OBJ
    CI1 --> CI2 --> CI3 --> CI4 -->|images| COMPOSE
```

### 2.1 Container responsibilities & tech-stack justifications

| Container | Tech | Responsibility | Why this choice (vs alternatives) |
|---|---|---|---|
| `postgres-15` | PostgreSQL 15.x | Primary persistence; RLS; triggers; materialised views | RLS native (SG-03); robust trigger model for `deny_update_delete` (CG-03); JSONB for `disclosure_notes` + `dq_findings.trigger_desc`; well-supported by SQLAlchemy 2 async / asyncpg. **Not MySQL**: weaker RLS support. **Not SQLite**: no RLS, no production hardening. |
| `fastapi_app` | FastAPI + Pydantic v2 + SQLAlchemy 2.x async + asyncpg | REST API, JWT auth, RBAC middleware, request validation, OpenAPI generation | Pydantic v2 gives 5–20× perf over v1 and is the validation layer for FR-30 POST inputs (SG-05). FastAPI auto-generates OpenAPI 3.1 (FR-29). Async stack accommodates rate-limited concurrency (NFR-11). **Not Flask**: weaker validation, no async-native. **Not Django**: heavy for read-mostly API. |
| `streamlit_app` | Streamlit 1.x + Plotly | Dashboard pages (KPI, drill-down, YoY, intensity, factor catalog, DQ, audit) | Streamlit chosen in requirements (AC-09); Plotly supports Okabe-Ito palette for NFR-22; native session_state simplifies state mgmt for single-user reporting tool. **Not React/Vue**: would require separate frontend pipeline; out of scope. |
| `etl_runner` | Python script (entrypoint) + pandas + pandera + structlog | Annual batch ETL: read CSV → validate → transform → DQ-gate → calc → write | Annual batch model per requirements.md §14.2; no Airflow/Prefect required for v1 (3 CSV files, ~150 rows). DAG-shaped pure-function pipeline keeps the door open for Prefect/Airflow adoption later. **Not Airflow**: operational overhead unjustified for tiny dataset. |
| `minio` | MinIO (S3-compatible) | Object storage for GO PDFs (CG-08, §2.4 of methodology_validation) and generated PDF/Excel artefacts | S3 API compatible — Phase-5+ swap to AWS S3 / GCS trivial. **Not local FS**: harder to back up; less audit-friendly. Optional in dev; required in prod. |
| `redis` | Redis 7 | Rate-limit counters (NFR-11), Streamlit/API caching | Standard rate-limit storage; future session caching. Optional v1 — in-memory fallback exists in slowapi / cachetools. |

### 2.2 Library pin policy

- **Pin to minor version** in `pyproject.toml`; **Renovate / Dependabot** in CI for automated minor/patch PRs (NFR-25, SG-11).
- **No floating versions** (no `>=`) in production deps; floating allowed only in `[project.optional-dependencies.dev]`.
- Reproducibility: `uv.lock` (or `poetry.lock`) committed; CI builds from lockfile.

---

## 3. Layered / Hexagonal Architecture

### 3.1 Folder organisation under `src/ghg_tool/`

```
src/ghg_tool/
├── domain/                     # Pure Python; NO framework imports.
│   ├── entities/
│   │   ├── emission.py         # EmissionRecord dataclass (frozen=True)
│   │   ├── emission_factor.py  # EmissionFactor (frozen)
│   │   ├── site.py             # Site (Codice_Sito, role, eu_ets_installation_id)
│   │   └── dq_finding.py       # DQFinding (frozen)
│   ├── value_objects/
│   │   ├── scope.py            # Scope = Literal[1, 2, 3]; SubScope enum
│   │   ├── gwp_set.py          # GWPSet = Literal["AR6", "AR5"]; GWP table values
│   │   ├── methodology.py      # Methodology enum
│   │   ├── codice_sito.py      # CodiceSito newtype with enum membership
│   │   └── tco2e.py            # decimal-backed Tco2e (Decimal(14,6))
│   ├── ports/                  # Abstract interfaces (Protocol classes)
│   │   ├── emissions_repository.py
│   │   ├── factor_repository.py
│   │   ├── dq_findings_repository.py
│   │   ├── audit_log_writer.py
│   │   └── object_store.py
│   └── policies/               # Pure invariants
│       ├── immutability.py     # raise on attempted mutation in-memory too
│       └── gwp_enforcement.py  # MG-10 mixed-set rejection
│
├── application/                # Use cases; orchestrates domain + ports.
│   ├── calc/                   # Per-scope calc modules (FR-05..FR-17, FR-34, FR-35)
│   │   ├── scope1_combustion.py
│   │   ├── scope1_process.py
│   │   ├── scope1_fugitive_zero.py
│   │   ├── scope2_lb.py
│   │   ├── scope2_mb.py
│   │   ├── scope3_cat1_purchased_goods.py
│   │   ├── scope3_cat2_capital_goods.py
│   │   ├── scope3_cat3_fuel_energy.py
│   │   ├── scope3_cat4_upstream_transport.py
│   │   ├── scope3_cat5_waste.py
│   │   ├── scope3_cat6_business_travel.py
│   │   ├── scope3_cat7_commuting.py
│   │   ├── scope3_cat9_downstream_transport.py
│   │   ├── scope3_cat11_zero_line.py
│   │   ├── scope3_cat12_eol.py
│   │   └── scope3_cat_omitted_zero_lines.py   # Cat 8/10/13/14/15
│   ├── services/               # Orchestrators
│   │   ├── ingestion_service.py     # FR-01/02/03/37 + DQ gates orchestration
│   │   ├── calculation_service.py   # Sequences the calc modules per FR-11 Σ S1 input
│   │   ├── correction_service.py    # FR-21 superseded_by workflow
│   │   ├── report_service.py        # PDF + Excel generation entrypoint
│   │   └── go_qc_service.py         # MG-14 QC1..QC8 evaluation
│   └── dto/                    # Pydantic v2 schemas for use-case I/O
│
├── infrastructure/             # Adapters: implement ports against external tech.
│   ├── persistence/
│   │   ├── alembic/            # Migration scripts (M0..M5)
│   │   ├── models.py           # SQLAlchemy 2.x declarative models
│   │   ├── emissions_repo.py   # Implements EmissionsRepository port
│   │   ├── factor_repo.py
│   │   ├── dq_findings_repo.py
│   │   └── audit_log_writer.py
│   ├── ingestion/
│   │   ├── csv_reader.py       # UTF-8 BOM + ; semicolon
│   │   └── pandera_schemas.py  # Schema per scope file
│   ├── reporting/
│   │   ├── pdf_weasyprint.py
│   │   ├── excel_openpyxl.py
│   │   └── templates/          # HTML/CSS for ESRS E1-6
│   ├── object_store/
│   │   └── minio_adapter.py
│   └── security/
│       ├── jwt.py              # SG-01 alg=none rejection
│       ├── password.py         # bcrypt
│       └── rls_session.py      # set_role / set local app.tenant_id / app.user_id
│
├── api/                        # FastAPI app.
│   ├── main.py
│   ├── routers/                # /auth, /emissions, /kpis, /audit-trail,
│   │   │                       # /factor-catalog, /dq-findings, /go-certificates,
│   │   │                       # /reports/pdf, /reports/excel, /health, /ready
│   ├── dependencies/           # JWT verify, role guard, DB session
│   ├── middleware/             # rate_limit (SG-10), correlation_id (FR-22),
│   │                           # structlog binding, PII redaction
│   └── schemas/                # Pydantic v2 request/response models
│
├── dashboard/                  # Streamlit pages.
│   ├── Home.py                 # KPI cards
│   ├── pages/
│   │   ├── 1_DrillDown.py
│   │   ├── 2_YoY.py            # VIANO 2025 banner per FR-24
│   │   ├── 3_Intensity.py      # FR-25
│   │   ├── 4_FactorCatalog.py
│   │   ├── 5_DQFindings.py
│   │   └── 6_AuditTrail.py
│   ├── components/             # KPI card, drill-down navigator, palette helper
│   └── i18n/                   # IT/EN dicts (FR-33)
│
└── etl/                        # DAG-shaped pipeline runner.
    ├── pipeline.py             # The 10-step linear DAG (Section 8)
    ├── steps/                  # One file per step (idempotent pure functions)
    └── manifests/              # Per-run JSON manifest (correlation_id, gwp_set, …)
```

### 3.2 Import-direction policy (one-way)

```
api  ─────┐
          ▼
  application ────► domain ◄──── infrastructure
          ▲
dashboard ┘
etl ──────► application ────► domain ◄──── infrastructure
```

- `domain` imports **nothing** outside `domain` (no FastAPI, no SQLAlchemy, no pandas). 100% unit-testable (NFR-15: 100% on calc modules).
- `application` imports `domain` + `application.dto`; depends on `domain.ports` only.
- `infrastructure` imports `domain` (to implement ports) + framework libs.
- `api` and `dashboard` and `etl` depend on `application`; never on `infrastructure` directly. Wiring is done in `api/main.py` (and `etl/pipeline.py`) via a small DI container.
- Enforced in CI via `import-linter` config (`importlinter.contract.layers`).

### 3.3 Why ports & adapters (rationale)

- **Testability** (NFR-15: 100% coverage on calc modules): `application.calc.*` accepts a `FactorCatalog` port and a GWP table — both injectable. Tests run without PostgreSQL.
- **Immutability invariants belong to the domain**, not the DB. Even before SQL trigger fires, the `EmissionRecord` is a frozen dataclass; mutation raises `FrozenInstanceError`. Defence in depth (SG-02).
- **AR5/AR6 swappability** (FR-19, FR-34, MG-10/12): GWP is a port; the same calc module produces a result for `gwp_set='AR6'` and `gwp_set='AR5'` deterministically.
- **Future transport swap**: if a Phase-6+ React frontend is introduced, the FastAPI router thins to a re-export over the same `application.services`; no change to calc.

---

## 4. Database Schema (PostgreSQL 15)

All tables live in the canonical database; **schema (namespace) split** is used to organise concerns and to anchor RLS policies. Schema layout:

- `raw.*` — Tier 1 staging (append-only)
- `ref.*` — Tier 2 reference (factor catalog, sites, GWP sets, users/roles, GO evidence)
- `calc.*` — Tier 3 computed (emissions_consolidated, audit_log, dq_findings, dlq)
- `mv.*` — Tier 4 materialised views & views

The single-tenant v1 constraint (requirements.md §14.1) is honoured by defaulting `tenant_id` to a fixed UUID; the column exists on every table so multi-tenant RLS can be added later without re-migration (AD-007).

### 4.1 Tier 1 — Raw / Staging (append-only)

```sql
-- Common: pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- v1 canonical tenant
CREATE TABLE ref.tenants (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code         VARCHAR(40) NOT NULL UNIQUE,
    legal_name   VARCHAR(200) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Seed:
-- INSERT INTO ref.tenants(code, legal_name)
-- VALUES ('CERAMIC_TILE_CO', '<official legal entity name>');

-- Ingestion batch correlation
CREATE TABLE raw.ingestion_batches (
    batch_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES ref.tenants(id),
    correlation_id      UUID NOT NULL,                         -- == batch_id for ETL-run; matches API write correlation
    run_started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_completed_at    TIMESTAMPTZ,
    etl_version         VARCHAR(40) NOT NULL,                  -- pyproject version
    gwp_set             VARCHAR(10) NOT NULL CHECK (gwp_set IN ('AR6','AR5')),
    triggered_by        VARCHAR(120) NOT NULL,                 -- user or 'cron'
    source_file_scope1_sha256  CHAR(64),
    source_file_scope2_sha256  CHAR(64),
    source_file_scope3_sha256  CHAR(64),
    notes               TEXT
);
CREATE INDEX ix_ingestion_batches_correlation ON raw.ingestion_batches(correlation_id);
CREATE INDEX ix_ingestion_batches_started     ON raw.ingestion_batches(run_started_at DESC);

-- Scope 1 raw rows: full CSV row capture incl. Fonte/Qualità/Stato + Note
CREATE TABLE raw.scope1_ingestions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES ref.tenants(id),
    batch_id            UUID NOT NULL REFERENCES raw.ingestion_batches(batch_id),
    -- CSV columns (FR-01):
    scope               SMALLINT NOT NULL CHECK (scope = 1),
    anno                INT NOT NULL CHECK (anno BETWEEN 2020 AND 2099),
    codice_sito         VARCHAR(40) NOT NULL,
    categoria_s1        VARCHAR(40) NOT NULL,
    combustibile        VARCHAR(40) NOT NULL,
    quantita            NUMERIC(20, 6) NOT NULL CHECK (quantita >= 0),
    unita               VARCHAR(20) NOT NULL,
    fonte_dato          VARCHAR(120) NOT NULL,
    qualita_dato        VARCHAR(4) NOT NULL,        -- P/D/E/U/S
    stato_dato          VARCHAR(20) NOT NULL,       -- Definitivo / Provvisorio / Stimato
    note                TEXT,                       -- nullable per FR-01
    -- ETL provenance (FR-01 zero-row, FR-37 default)
    provenance          VARCHAR(60),                -- e.g. 'native', 'auto_zero_user_confirmed'
    provenance_rationale TEXT,                      -- e.g. 'No gas connection 2024 — user 2026-05-13'
    -- Idempotency
    idempotency_key     VARCHAR(120) NOT NULL,      -- (codice_sito|anno|combustibile|provenance)
    -- Audit
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingested_by         VARCHAR(120) NOT NULL,
    UNIQUE (tenant_id, batch_id, idempotency_key)
);
CREATE INDEX ix_raw_s1_keys
   ON raw.scope1_ingestions(tenant_id, anno, codice_sito, combustibile);

-- Scope 2 raw rows: includes Strumento_MB column per requirements.md §6.2
CREATE TABLE raw.scope2_ingestions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES ref.tenants(id),
    batch_id            UUID NOT NULL REFERENCES raw.ingestion_batches(batch_id),
    scope               SMALLINT NOT NULL CHECK (scope = 2),
    anno                INT NOT NULL,
    codice_sito         VARCHAR(40) NOT NULL,
    voce_s2             VARCHAR(40) NOT NULL
                        CHECK (voce_s2 IN ('EE_Acquistata_GO', 'EE_Acquistata_Grid')),
    quantita            NUMERIC(20, 6) NOT NULL CHECK (quantita >= 0),
    unita               VARCHAR(20) NOT NULL CHECK (unita = 'kWh'),
    strumento_mb        VARCHAR(40),                -- GO_GSE / Grid_Residual / NULL
    fonte_dato          VARCHAR(120) NOT NULL,
    qualita_dato        VARCHAR(4) NOT NULL,
    stato_dato          VARCHAR(20) NOT NULL,
    note                TEXT,
    provenance          VARCHAR(60),                -- 'native' or 'auto_zero_user_confirmed'
    provenance_rationale TEXT,
    idempotency_key     VARCHAR(120) NOT NULL,      -- (codice_sito|anno|voce_s2|provenance)
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingested_by         VARCHAR(120) NOT NULL,
    UNIQUE (tenant_id, batch_id, idempotency_key)
);
CREATE INDEX ix_raw_s2_keys ON raw.scope2_ingestions(tenant_id, anno, codice_sito, voce_s2);

-- Scope 3 raw rows
CREATE TABLE raw.scope3_ingestions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES ref.tenants(id),
    batch_id            UUID NOT NULL REFERENCES raw.ingestion_batches(batch_id),
    scope               SMALLINT NOT NULL CHECK (scope = 3),
    anno                INT NOT NULL,
    categoria_s3        INT NOT NULL CHECK (categoria_s3 BETWEEN 1 AND 15),
    sottocategoria      VARCHAR(200) NOT NULL,
    metodo              VARCHAR(40) NOT NULL,       -- mass-based / spend-based / distance-based / activity-based
    combustibile        VARCHAR(40),                -- nullable for non-fuel rows
    quantita            NUMERIC(20, 6) NOT NULL CHECK (quantita >= 0),
    unita               VARCHAR(20) NOT NULL,
    fonte_dato          VARCHAR(120) NOT NULL,      -- after FR-37 default
    qualita_dato        VARCHAR(4) NOT NULL,        -- after FR-37 default
    stato_dato          VARCHAR(20) NOT NULL,       -- after FR-37 default
    note                TEXT,
    -- Defaulting provenance
    metadata_defaulted  BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE if FR-37 applied
    defaulting_rule_id  VARCHAR(20),                       -- 'FR-37-DEFAULT'
    idempotency_key     VARCHAR(160) NOT NULL,             -- (anno|categoria_s3|sottocategoria|combustibile)
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingested_by         VARCHAR(120) NOT NULL,
    UNIQUE (tenant_id, batch_id, idempotency_key)
);
CREATE INDEX ix_raw_s3_keys ON raw.scope3_ingestions(tenant_id, anno, categoria_s3, sottocategoria);

-- Block UPDATE/DELETE on raw tables (audit completeness)
CREATE OR REPLACE FUNCTION ops.deny_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = 'P0001',
        MESSAGE = format('Mutation forbidden on append-only table %I.%I',
                         TG_TABLE_SCHEMA, TG_TABLE_NAME);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_raw_s1_deny_mutation
BEFORE UPDATE OR DELETE ON raw.scope1_ingestions
FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
CREATE TRIGGER trg_raw_s2_deny_mutation
BEFORE UPDATE OR DELETE ON raw.scope2_ingestions
FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
CREATE TRIGGER trg_raw_s3_deny_mutation
BEFORE UPDATE OR DELETE ON raw.scope3_ingestions
FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
```

### 4.2 Tier 2 — Reference

```sql
-- 7 sites declared in requirements.md §5.2
CREATE TABLE ref.sites (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                UUID NOT NULL REFERENCES ref.tenants(id),
    codice_sito              VARCHAR(40) NOT NULL,
    full_name                VARCHAR(200) NOT NULL,
    role                     VARCHAR(80) NOT NULL,           -- 'Main' / 'Secondary'
    geography                VARCHAR(40) NOT NULL,           -- 'Italy'
    eu_ets_installation_id   VARCHAR(80),                    -- IANO only; nullable
    eu_ets_activity          VARCHAR(80),                    -- 'Annex I Activity 17'
    is_active                BOOLEAN NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, codice_sito)
);
-- Seed: IANO (EU ETS Activity 17), VIANO, VIANO_GARGOLA, CASALGRANDE,
--       FIORANO, SASSUOLO, FRASSINORO.

-- GWP sets (AR6 default, AR5 dual-track per MG-12)
CREATE TABLE ref.gwp_sets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gwp_set         VARCHAR(10) NOT NULL CHECK (gwp_set IN ('AR6','AR5')),
    substance       VARCHAR(40) NOT NULL,           -- 'CH4', 'N2O', 'SF6', 'HFC-134a', ...
    gwp100          NUMERIC(10, 3) NOT NULL,
    source_citation TEXT NOT NULL,                  -- 'IPCC AR6 WG1 Ch.7 SM Table 7.SM.7'
    valid_from      DATE NOT NULL,
    valid_to        DATE,
    UNIQUE (gwp_set, substance)
);
-- Seed AR6: CH4=27.9, N2O=273, SF6=25200, HFC-134a=1530, HFC-410A=2256,
--          HFC-32=771, CO2=1.
-- Seed AR5: CH4=28,   N2O=265, SF6=23500, HFC-134a=1300, HFC-410A=2088,
--          HFC-32=677, CO2=1.

-- Factor catalog (methodology_validation §11, 38 entries)
CREATE TABLE ref.factor_catalog (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES ref.tenants(id),
    factor_id       VARCHAR(80) NOT NULL,           -- e.g. 'WTT_GAS_NAT_DEFRA_2025'
    version         VARCHAR(40) NOT NULL,
    substance       VARCHAR(100) NOT NULL,
    scope           SMALLINT NOT NULL CHECK (scope BETWEEN 1 AND 3),
    category        VARCHAR(40) NOT NULL,           -- 'Cat 1' / 'Cat 3a' / 'LB' / ...
    source          VARCHAR(40) NOT NULL
                    CHECK (source IN ('DEFRA','ISPRA','IEA','ecoinvent','EXIOBASE',
                                      'CDP','IPCC','AIB','EPD','GHGProtocol')),
    value           NUMERIC(20, 8),                 -- nullable for LICENCE-restricted
    is_licence_only BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE when value cannot be republished
    unit            VARCHAR(40) NOT NULL,
    gwp_set         VARCHAR(10) NOT NULL CHECK (gwp_set IN ('AR6','AR5','n/a')),
    vintage         VARCHAR(40),                    -- '2024' / '2023+offset' / 'n/a'
    valid_from      DATE NOT NULL,
    valid_to        DATE,                           -- NULL = current
    applicability_note TEXT,
    pdf_source_uri  TEXT,                           -- e.g. minio path of DEFRA PDF
    published_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_by    VARCHAR(120) NOT NULL,
    is_published    BOOLEAN NOT NULL DEFAULT FALSE, -- mutable until publish, then frozen
    UNIQUE (tenant_id, factor_id, version, gwp_set)
);
CREATE INDEX ix_factor_catalog_lookup
   ON ref.factor_catalog(tenant_id, factor_id, gwp_set, valid_from DESC);

-- Immutability post-publish (MG-02)
CREATE OR REPLACE FUNCTION ops.deny_factor_mutation() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_published THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = format('Factor %s/%s is published and immutable',
                             OLD.factor_id, OLD.version);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_factor_immutable
BEFORE UPDATE OR DELETE ON ref.factor_catalog
FOR EACH ROW EXECUTE FUNCTION ops.deny_factor_mutation();

-- Constraint: factor_source NOT NULL (MG-04)
ALTER TABLE ref.factor_catalog
   ALTER COLUMN source SET NOT NULL,
   ADD CONSTRAINT chk_factor_source_nonblank
       CHECK (length(trim(source)) > 0);

-- GO certificate evidence (methodology_validation §2.4; CG-08; MG-14)
CREATE TABLE ref.go_certificate_evidence (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                   UUID NOT NULL REFERENCES ref.tenants(id),
    go_id                       VARCHAR(80) NOT NULL,    -- GSE unique ID
    site_id                     UUID NOT NULL REFERENCES ref.sites(id),
    anno                        INT NOT NULL,
    volume_mwh                  NUMERIC(20, 6) NOT NULL CHECK (volume_mwh >= 0),
    vintage_year                INT NOT NULL,
    cancellation_date           DATE NOT NULL,
    beneficiary_legal_entity    VARCHAR(200) NOT NULL,
    country_of_issuance         VARCHAR(40) NOT NULL,
    technology                  VARCHAR(40) NOT NULL,
    qc1_conveyed_claim_passed   BOOLEAN NOT NULL,
    qc2_unique_passed           BOOLEAN NOT NULL,
    qc3_redeemed_passed         BOOLEAN NOT NULL,
    qc4_vintage_passed          BOOLEAN NOT NULL,
    qc5_geographic_passed       BOOLEAN NOT NULL,
    qc6_scope_passed            BOOLEAN NOT NULL,
    qc7_exclusivity_passed      BOOLEAN NOT NULL,
    qc8_residual_mix_disclosed  BOOLEAN NOT NULL,
    pdf_evidence_uri            TEXT NOT NULL,           -- minio://gh-tool-evidence/<go_id>.pdf
    validated_by                VARCHAR(120) NOT NULL,
    validated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, go_id)
);
CREATE INDEX ix_go_evidence_site_year
   ON ref.go_certificate_evidence(tenant_id, site_id, anno);

-- Derived view: all 8 QC bool ANDed; used by MG-03 gate
CREATE VIEW ref.v_go_certificate_qc_pass AS
SELECT id, tenant_id, go_id, site_id, anno, volume_mwh,
       (qc1_conveyed_claim_passed AND qc2_unique_passed AND
        qc3_redeemed_passed AND qc4_vintage_passed AND
        qc5_geographic_passed AND qc6_scope_passed AND
        qc7_exclusivity_passed AND qc8_residual_mix_disclosed) AS all_qc_passed
FROM ref.go_certificate_evidence;

-- Users & roles (RBAC backing)
CREATE TABLE ref.roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_code   VARCHAR(40) NOT NULL UNIQUE,
            -- 'data_steward' / 'esg_manager' / 'auditor'
    description TEXT NOT NULL
);

CREATE TABLE ref.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES ref.tenants(id),
    username        VARCHAR(120) NOT NULL,
    email           VARCHAR(200) NOT NULL,
    password_hash   VARCHAR(200) NOT NULL,    -- bcrypt
    role_id         UUID NOT NULL REFERENCES ref.roles(id),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ,
    UNIQUE (tenant_id, username),
    UNIQUE (tenant_id, email)
);
```

### 4.3 Tier 3 — Computed & Audit

```sql
-- Emissions consolidated: append-only, bitemporal, supersedable
-- Schema follows requirements.md §10.1 exactly + factor_id FK + tenant_id.
CREATE TABLE calc.emissions_consolidated (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES ref.tenants(id),
    correlation_id      UUID NOT NULL,                          -- FK to ingestion_batches.correlation_id (logical)
    raw_row_id          UUID NOT NULL,                          -- references raw.scope{1,2,3}_ingestions.id; not a hard FK to allow Scope-3-only zero-line rows referring to virtual rows
    raw_scope           SMALLINT NOT NULL,                      -- helper for raw_row_id resolution
    scope               SMALLINT NOT NULL CHECK (scope IN (1,2,3)),
    sub_scope           VARCHAR(40) NOT NULL,
            -- 'combustion' | 'process' | 'fugitive' |
            -- 'LB' | 'MB' |
            -- 'Cat1' .. 'Cat15' | 'Cat3_WTT' | 'Cat3_TND'
    codice_sito         VARCHAR(40),                            -- NULL for corporate-level S3
    anno                INT NOT NULL,
    tco2e               NUMERIC(18, 6) NOT NULL CHECK (tco2e >= 0),
    co2_tonne           NUMERIC(18, 6),
    ch4_tco2e           NUMERIC(18, 6),
    n2o_tco2e           NUMERIC(18, 6),
    factor_id           UUID NOT NULL REFERENCES ref.factor_catalog(id),
    factor_version      VARCHAR(40) NOT NULL,
    factor_source       VARCHAR(40) NOT NULL,                   -- denormalised for fast audit query (CG-04)
    gwp_set             VARCHAR(10) NOT NULL CHECK (gwp_set IN ('AR6','AR5')),
    methodology         VARCHAR(40) NOT NULL,                   -- 'stoichiometric'/'spend-based'/'distance-based'/'activity-based'
    regulatory_stream   VARCHAR(40) NOT NULL DEFAULT 'CSRD_ESRS_E1',
            -- 'CSRD_ESRS_E1' (AR6) | 'EU_ETS_PHASE_IV' (AR5) (FR-34)
    calc_timestamp      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          VARCHAR(120) NOT NULL,
    -- Bitemporal validity
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to            TIMESTAMPTZ,                             -- NULL when active
    superseded_by       UUID REFERENCES calc.emissions_consolidated(id),
    reason_code         VARCHAR(40),
            -- on correction rows: 'DATA_ERROR'|'FACTOR_UPDATE'|'BOUNDARY_CHANGE'
            -- |'METHODOLOGY_REVISION'|'RESTATEMENT_>5PCT'
    disclosure_notes    TEXT,                                   -- ESRS narrative
    -- CG-04 non-null guard (defensive even though already NOT NULL above)
    CONSTRAINT chk_metadata_nonnull
        CHECK (factor_source IS NOT NULL AND
               factor_version IS NOT NULL AND
               gwp_set IS NOT NULL AND
               methodology IS NOT NULL),
    -- An active row has valid_to=NULL AND superseded_by=NULL
    CONSTRAINT chk_active_consistency
        CHECK ((valid_to IS NULL AND superseded_by IS NULL) OR
               (valid_to IS NOT NULL AND superseded_by IS NOT NULL))
);

-- Bitemporal partial unique index — at most one "active" row per natural key
-- (a "natural key" identifies the emission slot: scope + sub_scope + site +
-- year + regulatory_stream + gwp_set; tenancy implicit)
CREATE UNIQUE INDEX ux_emissions_active_natural_key
    ON calc.emissions_consolidated (
        tenant_id, scope, sub_scope, COALESCE(codice_sito,''),
        anno, regulatory_stream, gwp_set
    )
    WHERE valid_to IS NULL;

CREATE INDEX ix_emissions_scope_year_site
   ON calc.emissions_consolidated(tenant_id, scope, anno, codice_sito);
CREATE INDEX ix_emissions_correlation
   ON calc.emissions_consolidated(correlation_id);
CREATE INDEX ix_emissions_superseded
   ON calc.emissions_consolidated(superseded_by) WHERE superseded_by IS NOT NULL;

-- Strict immutability trigger (FR-20, NFR-14, NFR-21, CG-03)
-- General UPDATE/DELETE blocked. Correction workflow uses a SECURITY DEFINER
-- stored procedure that selectively allows updating valid_to/superseded_by/reason_code
-- on the *predecessor* row, gated by a session GUC set inside the procedure.
CREATE OR REPLACE FUNCTION ops.deny_emissions_mutation() RETURNS TRIGGER AS $$
DECLARE
    in_correction TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'DELETE forbidden on calc.emissions_consolidated';
    END IF;
    -- TG_OP = 'UPDATE'
    in_correction := current_setting('app.correction_in_progress', true);
    IF in_correction IS NULL OR in_correction <> 'true' THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'UPDATE forbidden on calc.emissions_consolidated outside the correction stored procedure';
    END IF;
    -- Even inside correction, restrict which columns may move:
    IF NEW.id            <> OLD.id            OR
       NEW.tco2e         <> OLD.tco2e         OR
       NEW.factor_id     <> OLD.factor_id     OR
       NEW.factor_version <> OLD.factor_version OR
       NEW.gwp_set       <> OLD.gwp_set       OR
       NEW.methodology   <> OLD.methodology   OR
       NEW.scope         <> OLD.scope         OR
       NEW.anno          <> OLD.anno          OR
       NEW.codice_sito   IS DISTINCT FROM OLD.codice_sito THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'Correction may only set valid_to, superseded_by, reason_code';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_emissions_deny_mutation
BEFORE UPDATE OR DELETE ON calc.emissions_consolidated
FOR EACH ROW EXECUTE FUNCTION ops.deny_emissions_mutation();

-- Correction stored procedure (FR-21)
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
    PERFORM set_config('app.correction_in_progress','true', true);  -- local txn
    UPDATE calc.emissions_consolidated
       SET valid_to = now(),
           superseded_by = p_new_id,
           reason_code  = p_reason_code
     WHERE id = p_predecessor_id
       AND valid_to IS NULL;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Predecessor row not found or already superseded: %', p_predecessor_id;
    END IF;
    PERFORM set_config('app.correction_in_progress','false', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- dq_findings: data_quality_report §13.2 + parent_finding_id lineage
CREATE TABLE calc.dq_findings (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES ref.tenants(id),
    correlation_id          UUID NOT NULL,
    parent_finding_id       UUID REFERENCES calc.dq_findings(id),  -- chains REMEDIATED → original
    rule_id                 VARCHAR(40) NOT NULL,
            -- e.g. 'DQ-CRIT-01','DQ-WARN-06','FR-37-DEFAULT','INFO-02'
    severity                VARCHAR(10) NOT NULL
                            CHECK (severity IN ('CRIT','WARN','INFO')),
    scope                   SMALLINT,
    codice_sito             VARCHAR(40),
    anno                    INT,
    metric                  VARCHAR(100),
    value_observed          NUMERIC(20, 6),
    value_reference         NUMERIC(20, 6),
    ratio_yoy               NUMERIC(20, 6),
    z_score                 NUMERIC(20, 6),
    trigger_desc            TEXT,
    recommended_action      TEXT,
    raw_row_id              UUID,                  -- soft FK to raw.*_ingestions.id
    blocks_pipeline         BOOLEAN NOT NULL DEFAULT FALSE,
    dq_report_version       VARCHAR(40) NOT NULL,
    assessed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolution_status       VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                            CHECK (resolution_status IN ('OPEN','WAIVED','REMEDIATED')),
    waiver_reason_code      VARCHAR(40),
            -- 'OPERATIONAL_ANNOTATION' | 'USER_CONFIRMED_ZERO' | 'METHODOLOGY_INFO'
    waiver_justification    TEXT,
    waiver_approved_by      VARCHAR(120),
    resolved_at             TIMESTAMPTZ
);
CREATE INDEX ix_dq_findings_rule_sev
   ON calc.dq_findings(tenant_id, rule_id, severity);
CREATE INDEX ix_dq_findings_correlation
   ON calc.dq_findings(correlation_id);
CREATE INDEX ix_dq_findings_unresolved
   ON calc.dq_findings(tenant_id) WHERE resolution_status = 'OPEN';

CREATE TRIGGER trg_dq_findings_deny_mutation
BEFORE UPDATE OR DELETE ON calc.dq_findings
FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
-- NOTE: dq_findings is append-only; resolution writes a NEW row with
-- parent_finding_id set and resolution_status='REMEDIATED'/'WAIVED'.

-- DLQ (Dead Letter Queue) per data_quality_report §13.1, NFR-13
CREATE TABLE calc.dlq (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES ref.tenants(id),
    correlation_id      UUID NOT NULL,
    dq_finding_id       UUID REFERENCES calc.dq_findings(id),
    rule_id             VARCHAR(40) NOT NULL,
    severity            VARCHAR(10) NOT NULL CHECK (severity IN ('CRIT','WARN')),
    scope               SMALLINT NOT NULL,
    codice_sito         VARCHAR(40),
    anno                INT,
    combustibile_or_voce VARCHAR(60),
    raw_row_payload     JSONB NOT NULL,         -- full original row
    value_observed      NUMERIC(20, 6),
    threshold           VARCHAR(120),
    z_score             NUMERIC(20, 6),
    ratio_yoy           NUMERIC(20, 6),
    fired_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    message             TEXT NOT NULL,
    replay_status       VARCHAR(20) NOT NULL DEFAULT 'PENDING'
                        CHECK (replay_status IN ('PENDING','REPLAYED','ABANDONED')),
    replayed_at         TIMESTAMPTZ,
    replayed_by         VARCHAR(120)
);
CREATE INDEX ix_dlq_correlation ON calc.dlq(correlation_id);
CREATE INDEX ix_dlq_unresolved  ON calc.dlq(tenant_id) WHERE replay_status='PENDING';
CREATE TRIGGER trg_dlq_deny_mutation
BEFORE UPDATE OR DELETE ON calc.dlq
FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
-- Note: dlq.replay_status is updated by a SECURITY DEFINER procedure analogous
-- to fn_emit_correction; the trigger above is replaced for dlq with a
-- "restricted columns" variant identical in spirit to the emissions trigger.
-- For brevity the variant is omitted here.

-- audit_log: every API write op + sensitive read op
CREATE TABLE calc.audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES ref.tenants(id),
    correlation_id  UUID NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         UUID REFERENCES ref.users(id),
    user_role       VARCHAR(40) NOT NULL,
    action          VARCHAR(60) NOT NULL,
            -- 'ingest.run' | 'ingest.batch_insert' | 'calc.emit' |
            -- 'correction.apply' | 'pdf.generate' | 'excel.generate' |
            -- 'factor.publish' | 'go.qc.upsert' | 'dq.waiver' | 'dlq.replay' |
            -- 'audit.read' | 'login.success' | 'login.failure'
    resource        VARCHAR(60),                   -- table or domain object name
    resource_id     UUID,
    request_method  VARCHAR(10),
    request_path    TEXT,
    status_code     SMALLINT,
    ip_address      INET,
    user_agent      TEXT,
    before_state    JSONB,                         -- only for correction operations
    after_state     JSONB,
    extra           JSONB                          -- additional structured context
);
CREATE INDEX ix_audit_log_user_time ON calc.audit_log(user_id, occurred_at DESC);
CREATE INDEX ix_audit_log_action    ON calc.audit_log(action, occurred_at DESC);
CREATE TRIGGER trg_audit_log_deny_mutation
BEFORE UPDATE OR DELETE ON calc.audit_log
FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
```

### 4.4 Tier 4 — Materialised view + audit view

```sql
-- Top-level KPI summary feeding the Streamlit Home page (NFR-02 < 5s cold load)
CREATE MATERIALIZED VIEW mv.mv_kpi_summary AS
SELECT
    e.tenant_id,
    e.regulatory_stream,
    e.gwp_set,
    e.anno,
    e.scope,
    e.sub_scope,
    e.codice_sito,
    SUM(e.tco2e) AS tco2e_total,
    COUNT(*)     AS row_count,
    MAX(e.calc_timestamp) AS last_calc_at
FROM calc.emissions_consolidated e
WHERE e.valid_to IS NULL                          -- active rows only
GROUP BY e.tenant_id, e.regulatory_stream, e.gwp_set,
         e.anno, e.scope, e.sub_scope, e.codice_sito;

CREATE UNIQUE INDEX ux_mv_kpi_summary
   ON mv.mv_kpi_summary(tenant_id, regulatory_stream, gwp_set,
                        anno, scope, sub_scope, COALESCE(codice_sito,''));

-- Refreshed at end of ETL run; concurrent variant so dashboard reads never block.
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mv.mv_kpi_summary;

-- v_audit_trail: joins emissions ← factor ← raw_ingestion. Used by /audit-trail.
CREATE OR REPLACE VIEW mv.v_audit_trail AS
SELECT
    e.id                       AS emission_id,
    e.tenant_id,
    e.correlation_id,
    e.scope,
    e.sub_scope,
    e.codice_sito,
    e.anno,
    e.tco2e,
    e.co2_tonne, e.ch4_tco2e, e.n2o_tco2e,
    e.gwp_set,
    e.regulatory_stream,
    e.methodology,
    e.calc_timestamp,
    e.created_by,
    e.valid_from, e.valid_to, e.superseded_by, e.reason_code,
    e.disclosure_notes,
    -- Factor metadata
    f.factor_id  AS factor_id_code,
    f.version    AS factor_version,
    f.source     AS factor_source,
    f.value      AS factor_value,
    f.unit       AS factor_unit,
    f.vintage    AS factor_vintage,
    f.pdf_source_uri AS factor_source_pdf,
    -- Raw row metadata (resolved via raw_scope discriminator)
    CASE e.raw_scope
        WHEN 1 THEN (SELECT row_to_json(r1) FROM raw.scope1_ingestions r1 WHERE r1.id = e.raw_row_id)
        WHEN 2 THEN (SELECT row_to_json(r2) FROM raw.scope2_ingestions r2 WHERE r2.id = e.raw_row_id)
        WHEN 3 THEN (SELECT row_to_json(r3) FROM raw.scope3_ingestions r3 WHERE r3.id = e.raw_row_id)
    END AS raw_row_json
FROM calc.emissions_consolidated e
JOIN ref.factor_catalog f ON f.id = e.factor_id;
```

### 4.5 Indexing summary

| Index | Table | Purpose |
|---|---|---|
| `ix_emissions_scope_year_site` | calc.emissions_consolidated | FR-23 drill-down: filter by (scope, year, site) |
| `ix_emissions_correlation` | calc.emissions_consolidated | FR-22 audit trail: trace by correlation_id |
| `ix_emissions_superseded` | calc.emissions_consolidated | FR-21: corrections chain traversal |
| `ux_emissions_active_natural_key` | calc.emissions_consolidated | Bitemporal invariant: ≤1 active row per natural key |
| `ix_factor_catalog_lookup` | ref.factor_catalog | Calc-time factor selection by (factor_id, gwp_set, vintage) |
| `ix_dq_findings_rule_sev` | calc.dq_findings | FR-32 / KPI-13 — findings dashboard |
| `ix_dq_findings_correlation` | calc.dq_findings | DQ findings for a given run |
| `ix_audit_log_user_time` | calc.audit_log | Auditor: "what did user X do last?" |
| `ix_dlq_unresolved` | calc.dlq | NFR-13 replay UI |
| `ix_raw_s{1,2,3}_keys` | raw.scope{1,2,3}_ingestions | DQ reconciliation queries |
| `ix_go_evidence_site_year` | ref.go_certificate_evidence | MB calc time lookup (MG-03) |

### 4.6 Migration strategy (Alembic)

Sub-deliverable-aligned revisions (AD-009):

| Revision | Tag | Contents |
|---|---|---|
| `M0_base_schema` | `0001_M0` | extensions (pgcrypto), schemas (raw, ref, calc, mv, ops), `ops.deny_mutation()` |
| `M1_emissions_immutability` | `0002_M1` | `ref.tenants`, `ref.sites`, `calc.emissions_consolidated`, immutability trigger, `fn_emit_correction`, audit_log |
| `M2_factor_catalog` | `0003_M2` | `ref.gwp_sets`, `ref.factor_catalog` + immutability + non-null source constraint; seed AR6/AR5; placeholder rows for §11 catalog |
| `M3_dq_findings_dlq` | `0004_M3` | `calc.dq_findings`, `calc.dlq`, append-only triggers, `raw.ingestion_batches`, raw staging tables |
| `M4_rls_policies` | `0005_M4` | `ref.roles`, `ref.users`, RLS policies (see §5) |
| `M5_views_materialized` | `0006_M5` | `mv.mv_kpi_summary`, `mv.v_audit_trail`, GO certificate evidence, materialised view refresh procedure |

Operational rule: production migrations require explicit manual approval (no auto-run in prod, see §15). Non-prod environments auto-migrate on container start.

---

## 5. RBAC & RLS Design

### 5.1 Roles

| Role | Scope of authority | requirement source |
|---|---|---|
| `data_steward` | Ingest raw data; publish factor catalog rows (cannot un-publish); upsert GO QC checklist; assert DQ findings; replay DLQ. Cannot approve PDF, cannot waive DQ-CRIT. | requirements.md §3, SG-12 |
| `esg_manager` | Read everything; approve / generate PDF + Excel; waive DQ-WARN with reason_code; emit corrections (FR-21). Cannot ingest raw data directly (SG-12 separation of duties). | requirements.md §3, FR-31, SG-12 |
| `auditor` | Read-only across all tables, with the exception of `ref.users.password_hash` (column-level deny). May export Excel for offline review but not generate the official PDF. | requirements.md §3 |

### 5.2 Permission matrix (concise)

| Table | data_steward | esg_manager | auditor |
|---|---|---|---|
| `raw.scope{1,2,3}_ingestions` | SELECT, INSERT | SELECT | SELECT |
| `raw.ingestion_batches` | SELECT, INSERT | SELECT | SELECT |
| `ref.factor_catalog` | SELECT, INSERT (publish only) | SELECT | SELECT |
| `ref.gwp_sets` | SELECT | SELECT | SELECT |
| `ref.sites` | SELECT | SELECT, INSERT | SELECT |
| `ref.go_certificate_evidence` | SELECT, INSERT, UPDATE pre-validation only* | SELECT | SELECT |
| `ref.users` (rows) | SELECT (own row) | SELECT (own row) | SELECT (own row) |
| `ref.users.password_hash` (column) | DENY | DENY | **DENY** (explicit) |
| `calc.emissions_consolidated` | INSERT | INSERT (via correction proc) | SELECT |
| `calc.dq_findings` | SELECT, INSERT | SELECT, INSERT (waiver via proc) | SELECT |
| `calc.dlq` | SELECT, INSERT, REPLAY (proc) | SELECT | SELECT |
| `calc.audit_log` | SELECT (own actions) | SELECT (own actions) | SELECT (all) |
| `mv.*` | SELECT | SELECT | SELECT |

*GO evidence has a one-shot publish moment: once `qc1..qc8` booleans are saved and the evidence is referenced by an emission row's factor, further mutation requires a correction workflow. Enforced by application-layer pre-check + audit-log entry.

### 5.3 RLS policy examples (concrete `CREATE POLICY` DDL)

```sql
-- Enable RLS
ALTER TABLE calc.emissions_consolidated ENABLE ROW LEVEL SECURITY;
ALTER TABLE calc.emissions_consolidated FORCE ROW LEVEL SECURITY;

ALTER TABLE raw.scope1_ingestions ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw.scope1_ingestions FORCE ROW LEVEL SECURITY;
-- (same for scope2/3_ingestions, ingestion_batches, dq_findings, dlq, audit_log, factor_catalog, go_certificate_evidence)

-- DB roles map to RBAC roles; created in M4.
-- The application connects as 'app_user' and SETs session GUCs:
--   SET LOCAL app.tenant_id = '<uuid>';
--   SET LOCAL app.user_id   = '<uuid>';
--   SET LOCAL app.role_code = 'data_steward' | 'esg_manager' | 'auditor';

-- Tenant isolation
CREATE POLICY p_emissions_tenant_isolation
ON calc.emissions_consolidated
USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- auditor: SELECT only
CREATE POLICY p_emissions_auditor_select
ON calc.emissions_consolidated
FOR SELECT
USING (current_setting('app.role_code') = 'auditor');

-- data_steward: INSERT only (no SELECT-filtering beyond tenant)
CREATE POLICY p_emissions_steward_insert
ON calc.emissions_consolidated
FOR INSERT
WITH CHECK (current_setting('app.role_code') = 'data_steward'
            AND tenant_id = current_setting('app.tenant_id')::uuid);

-- esg_manager: INSERT (corrections) + SELECT
CREATE POLICY p_emissions_esg_select
ON calc.emissions_consolidated
FOR SELECT
USING (current_setting('app.role_code') = 'esg_manager');

CREATE POLICY p_emissions_esg_insert
ON calc.emissions_consolidated
FOR INSERT
WITH CHECK (current_setting('app.role_code') = 'esg_manager'
            AND tenant_id = current_setting('app.tenant_id')::uuid);

-- Column-level deny on password_hash for auditor
REVOKE SELECT (password_hash) ON ref.users FROM PUBLIC;
GRANT SELECT (id, tenant_id, username, email, role_id, is_active,
              created_at, last_login_at)
    ON ref.users TO app_role_auditor;
GRANT SELECT, INSERT, UPDATE (password_hash, last_login_at)
    ON ref.users TO app_role_authenticator;     -- service account for login flow

-- raw.scope1_ingestions: data_steward INSERT, all roles SELECT
CREATE POLICY p_raw_s1_select_all
ON raw.scope1_ingestions
FOR SELECT
USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY p_raw_s1_insert_steward
ON raw.scope1_ingestions
FOR INSERT
WITH CHECK (current_setting('app.role_code') = 'data_steward'
            AND tenant_id = current_setting('app.tenant_id')::uuid);

-- factor_catalog: only data_steward inserts; all roles SELECT
CREATE POLICY p_factor_insert_steward
ON ref.factor_catalog
FOR INSERT
WITH CHECK (current_setting('app.role_code') = 'data_steward'
            AND tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY p_factor_select_all
ON ref.factor_catalog
FOR SELECT
USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- dq_findings: data_steward INSERT, esg_manager INSERT (waivers via proc)
CREATE POLICY p_dq_insert_steward
ON calc.dq_findings
FOR INSERT
WITH CHECK (current_setting('app.role_code') IN ('data_steward','esg_manager')
            AND tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY p_dq_select_all
ON calc.dq_findings
FOR SELECT
USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

### 5.4 Defence-in-depth (SG-02)

Two layers of enforcement are intentional:

| Layer | Mechanism | What it stops |
|---|---|---|
| FastAPI middleware | JWT decode → role claim → endpoint-level `Depends(require_role("esg_manager"))` | A 401/403 long before SQL touches a row; cheap; informative error. |
| PostgreSQL RLS + `FORCE ROW LEVEL SECURITY` | Session GUCs `app.tenant_id` / `app.role_code` set per request | Defence even if an SQL-injection or misrouted query reaches the DB layer with a bad role — DB still refuses. |

Both layers are independently tested in CI: the API tests assert HTTP 401/403 (SG-01/SG-02); a separate pgTAP / pytest+psycopg test bypasses the API and sets bogus GUCs directly to assert RLS still denies.

### 5.5 JWT claims

```json
{
  "sub": "<user_uuid>",
  "tenant_id": "<tenant_uuid>",         // future multi-tenant
  "role": "data_steward",
  "iat": 1715553600,
  "exp": 1715557200,                    // max 1h access (NFR-05)
  "jti": "<token_uuid>",                // revocation list lookup
  "iss": "ghg-tool",
  "aud": "ghg-tool-api"
}
```

- `alg=HS256` minimum, `RS256` recommended in prod (NFR-05). Key rotated quarterly.
- `alg=none` explicitly rejected (SG-01) by `python-jose` `decode(..., algorithms=["RS256"])` whitelist.
- Refresh token: 24h, distinct `jti`, stored hashed in a `ref.refresh_tokens` table (not shown above) for revocation.

---

## 6. FastAPI Application Structure

### 6.1 Routers

| Router | Methods | Role(s) | requirement |
|---|---|---|---|
| `/auth` | `POST /login`, `POST /refresh`, `POST /logout` | public / authenticated | NFR-05, SG-01 |
| `/emissions` | `GET /`, `GET /{id}`, `POST /`, `GET /corrections/{id}` | GET: all; POST: data_steward | FR-29, FR-30, FR-21 |
| `/kpis` | `GET /` | all | FR-23, FR-24, FR-25 |
| `/audit-trail` | `GET /` | auditor (priority) + all | FR-22 |
| `/factor-catalog` | `GET /`, `POST /` | GET: all; POST: data_steward | FR-04, MG-01 |
| `/dq-findings` | `GET /`, `POST /waivers` | GET: all; POST: esg_manager | FR-32, KPI-13 |
| `/go-certificates` | `GET /`, `POST /`, `PATCH /{id}` | data_steward (CRUD); auditor SELECT | MG-14, CG-08 |
| `/reports/pdf` | `POST /` | esg_manager | FR-28, CG-06, CG-07 |
| `/reports/excel` | `POST /` | esg_manager, data_steward | FR-27 |
| `/health` | `GET /` | public | NFR-24 |
| `/ready` | `GET /` | public | NFR-24 |
| `/metrics` | `GET /` | internal (basic auth, scrape) | observability (§13) |

### 6.2 OpenAPI specimens

#### 6.2.1 `POST /auth/login` (login)

```yaml
paths:
  /auth/login:
    post:
      summary: Authenticate user and issue JWT
      security: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [username, password]
              properties:
                username: { type: string, minLength: 3, maxLength: 120 }
                password: { type: string, minLength: 8, format: password }
      responses:
        '200':
          description: Authenticated
          content:
            application/json:
              schema:
                type: object
                required: [access_token, refresh_token, token_type, expires_in, role]
                properties:
                  access_token:  { type: string }
                  refresh_token: { type: string }
                  token_type:    { type: string, enum: [Bearer] }
                  expires_in:    { type: integer, example: 3600 }
                  role:          { type: string, enum: [data_steward, esg_manager, auditor] }
        '401':
          $ref: '#/components/responses/Unauthorised'
        '429':
          $ref: '#/components/responses/RateLimited'
```

#### 6.2.2 `POST /emissions` (append-only write)

```yaml
paths:
  /emissions:
    post:
      summary: Append an emission row (data_steward only)
      security: [{ bearerAuth: [] }]
      parameters:
        - in: header
          name: Idempotency-Key
          required: true
          schema: { type: string, minLength: 16, maxLength: 64 }
        - in: header
          name: X-Correlation-Id
          schema: { type: string, format: uuid }
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - scope
                - sub_scope
                - anno
                - tco2e
                - factor_id
                - factor_version
                - gwp_set
                - methodology
                - raw_row_id
                - raw_scope
              properties:
                scope:           { type: integer, enum: [1, 2, 3] }
                sub_scope:       { type: string,
                                  enum: [combustion, process, fugitive,
                                         LB, MB,
                                         Cat1, Cat2, Cat3_WTT, Cat3_TND,
                                         Cat4, Cat5, Cat6, Cat7, Cat8,
                                         Cat9, Cat10, Cat11, Cat12,
                                         Cat13, Cat14, Cat15] }
                codice_sito:     { type: string, nullable: true,
                                  enum: [IANO, VIANO, VIANO_GARGOLA, CASALGRANDE,
                                         FIORANO, SASSUOLO, FRASSINORO, null] }
                anno:            { type: integer, minimum: 2020, maximum: 2099 }
                tco2e:           { type: number, format: double, minimum: 0 }
                co2_tonne:       { type: number, format: double, nullable: true }
                ch4_tco2e:       { type: number, format: double, nullable: true }
                n2o_tco2e:       { type: number, format: double, nullable: true }
                factor_id:       { type: string, format: uuid }
                factor_version:  { type: string }
                gwp_set:         { type: string, enum: [AR6, AR5] }
                methodology:     { type: string,
                                  enum: [stoichiometric, spend-based,
                                         distance-based, activity-based,
                                         mass-based, declared-zero] }
                regulatory_stream:{ type: string,
                                  enum: [CSRD_ESRS_E1, EU_ETS_PHASE_IV] }
                raw_row_id:      { type: string, format: uuid }
                raw_scope:       { type: integer, enum: [1, 2, 3] }
                disclosure_notes:{ type: string, nullable: true }
      responses:
        '201':
          description: Emission row created
          headers:
            X-Correlation-Id:
              schema: { type: string, format: uuid }
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:             { type: string, format: uuid }
                  correlation_id: { type: string, format: uuid }
                  valid_from:     { type: string, format: date-time }
        '401': { $ref: '#/components/responses/Unauthorised' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '409':
          description: Idempotency conflict (replay)
          content:
            application/problem+json:
              schema: { $ref: '#/components/schemas/Problem' }
        '422':
          description: Validation error
          content:
            application/problem+json:
              schema: { $ref: '#/components/schemas/Problem' }
        '429': { $ref: '#/components/responses/RateLimited' }
```

#### 6.2.3 `GET /audit-trail` (auditor-friendly view)

```yaml
paths:
  /audit-trail:
    get:
      summary: Full lineage view (emissions ← factor ← raw_row), filterable
      security: [{ bearerAuth: [] }]
      parameters:
        - { in: query, name: scope, schema: { type: integer, enum: [1,2,3] } }
        - { in: query, name: anno,  schema: { type: integer } }
        - { in: query, name: codice_sito,
            schema: { type: string,
                      enum: [IANO, VIANO, VIANO_GARGOLA, CASALGRANDE,
                             FIORANO, SASSUOLO, FRASSINORO] } }
        - { in: query, name: gwp_set, schema: { type: string, enum: [AR6, AR5] } }
        - { in: query, name: regulatory_stream,
            schema: { type: string, enum: [CSRD_ESRS_E1, EU_ETS_PHASE_IV] } }
        - { in: query, name: correlation_id, schema: { type: string, format: uuid } }
        - { in: query, name: include_superseded, schema: { type: boolean, default: false } }
        - { in: query, name: limit,   schema: { type: integer, maximum: 1000, default: 100 } }
        - { in: query, name: offset,  schema: { type: integer, default: 0 } }
      responses:
        '200':
          description: Audit trail page
          content:
            application/json:
              schema:
                type: object
                properties:
                  total:    { type: integer }
                  rows:
                    type: array
                    items:
                      type: object
                      properties:
                        emission_id:        { type: string, format: uuid }
                        scope:              { type: integer }
                        sub_scope:          { type: string }
                        codice_sito:        { type: string, nullable: true }
                        anno:               { type: integer }
                        tco2e:              { type: number }
                        factor_id_code:     { type: string }
                        factor_version:     { type: string }
                        factor_source:      { type: string }
                        factor_value:       { type: number, nullable: true }
                        factor_unit:        { type: string }
                        factor_source_pdf:  { type: string, format: uri, nullable: true }
                        gwp_set:            { type: string }
                        methodology:        { type: string }
                        calc_timestamp:     { type: string, format: date-time }
                        valid_from:         { type: string, format: date-time }
                        valid_to:           { type: string, format: date-time, nullable: true }
                        superseded_by:      { type: string, format: uuid, nullable: true }
                        reason_code:        { type: string, nullable: true }
                        raw_row:            { type: object, additionalProperties: true }
        '401': { $ref: '#/components/responses/Unauthorised' }
        '429': { $ref: '#/components/responses/RateLimited' }

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  responses:
    Unauthorised:
      description: Missing/invalid token
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
    Forbidden:
      description: Role denied
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
    RateLimited:
      description: Rate limit exceeded
      headers:
        Retry-After: { schema: { type: integer } }
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
  schemas:
    Problem:                               # RFC 7807
      type: object
      properties:
        type:     { type: string, format: uri }
        title:    { type: string }
        status:   { type: integer }
        detail:   { type: string }
        instance: { type: string }
        correlation_id: { type: string, format: uuid }
        errors:
          type: array
          items:
            type: object
            properties:
              loc:    { type: array, items: { type: string } }
              msg:    { type: string }
              type:   { type: string }
```

### 6.3 Cross-cutting middleware

| Middleware | Order | Function |
|---|---|---|
| `CorrelationIdMiddleware` | 1 | Read `X-Correlation-Id` header; if absent, generate UUID; bind to `structlog.contextvars`; echo on response (FR-22). |
| `RequestLoggingMiddleware` | 2 | Structured JSON log on entry + exit (Section 13); PII redaction list applied (NFR-08, SG-07). |
| `RateLimitMiddleware` (slowapi/redis) | 3 | 100 req/min/user authenticated; 20 req/min unauthenticated; 429 with `Retry-After` (NFR-11, SG-10). |
| `AuthMiddleware` | 4 | JWT decode → User + role + tenant; `alg=none` rejection (SG-01). |
| `RLSContextMiddleware` | 5 | Open DB session; `SET LOCAL app.tenant_id`, `app.user_id`, `app.role_code` from JWT claims. |
| `ProblemDetailExceptionHandler` | 6 | All errors → RFC 7807 `application/problem+json`; never leak stack traces (NFR-08). |
| `AuditLogMiddleware` | 7 | After successful write-method responses, append a row to `calc.audit_log` with action + before/after (for corrections). |

### 6.4 PII redaction policy (NFR-08, SG-07)

Structured log fields drop-listed (never serialised, never emitted):
- `password`, `password_hash`, `token`, `access_token`, `refresh_token`, `Authorization` (header)
- Any field whose name matches regex `(?i)(email|fiscal_code|codice_fiscale|tax_id|cf|piva|vat)`
- Free-text fields scanned for Italian fiscal-code shape `[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]` are masked

Allow-listed identifiers: `username` (logged), `user_id` (UUID, logged), `tenant_id` (UUID, logged), `correlation_id`.

---

## 7. ETL Pipeline Design

### 7.1 DAG (linear v1, DAG-shaped for future Prefect/Airflow adoption)

```mermaid
graph TB
    S0["0. open_batch<br/>(create raw.ingestion_batches row;<br/>correlation_id = batch_id;<br/>gwp_set ∈ {AR6, AR5})"]
    S1["1. read_csv<br/>(scope1, scope2, scope3;<br/>UTF-8 BOM, ; delim; checksum)"]
    S2["2. pandera_validate<br/>(per-scope schemas; reject malformed rows)"]
    S3["3. etl_synthesise<br/>FR-01: VIANO_GARGOLA GAS_NAT 2024 zero<br/>FR-02: SASSUOLO Grid 2025 zero<br/>FR-37: Cat 3 metadata default<br/>FR-35: Fugitive HFC zero<br/>FR-36: Cat 8/10/13/14/15 zero"]
    S4["4. dq_gates<br/>(MG-04 NULL guard;<br/>DQ-CRIT-01..05 / DQ-WARN-01..08;<br/>CRIT → DLQ; WARN → annotate)"]
    S5["5. persist_raw<br/>(raw.scope{1,2,3}_ingestions INSERT)"]
    S6["6. factor_apply<br/>(per-scope calc modules<br/>read ref.factor_catalog;<br/>apply gwp_sets table)"]
    S7["7. recon_S1_cat3<br/>(FR-11 Σ Scope 1 input for Cat 3;<br/>log delta to dq_findings)"]
    S8["8. persist_emissions<br/>(calc.emissions_consolidated INSERT;<br/>dual-write AR6 + AR5 if MG-12 active)"]
    S9["9. mv_refresh<br/>(REFRESH MATERIALIZED VIEW CONCURRENTLY<br/>mv.mv_kpi_summary)"]
    S10["10. close_batch<br/>(set run_completed_at;<br/>notify esg_manager + data_steward;<br/>audit_log entry)"]

    S0 --> S1 --> S2 --> S3 --> S4 -->|pass| S5
    S4 -.->|CRIT row| DLQ[("calc.dlq")]
    S5 --> S6 --> S7 --> S8 --> S9 --> S10
```

### 7.2 Step-by-step (idempotency, retry, logging)

| Step | Pure / Side-effectful | Idempotency key | Retry policy | Structured log fields |
|---|---|---|---|---|
| 0. open_batch | Side | `correlation_id` (caller-supplied for replay) | none | step, correlation_id, gwp_set, etl_version |
| 1. read_csv | Pure-ish (file system) | `sha256(file)` recorded on batch | 3× exp-backoff 0.5/1/2s on IOError | step, file, row_count, sha256 |
| 2. pandera_validate | Pure | row hash | none (deterministic) | step, schema_errors_count, sample_failing_row_hashes |
| 3. etl_synthesise | Pure | `(codice_sito, anno, combustibile/voce, provenance)` | none | step, fr01_zero_inserted, fr02_zero_inserted, fr37_defaulted_rows, fr35_fugitive_zero_inserted, fr36_omitted_zero_inserted |
| 4. dq_gates | Pure | `(rule_id, idempotency_key)` | none | step, crit_count, warn_count, info_count, dlq_rows |
| 5. persist_raw | Side | `(batch_id, idempotency_key)` UNIQUE in DB | 5× exp-backoff on TransientDBError; abort on `UniqueViolation` and record as DUPLICATE in DLQ | step, rows_inserted, rows_skipped_duplicate |
| 6. factor_apply | Pure | `(emission_natural_key, factor_id, factor_version, gwp_set)` | none | step, scope, sub_scope, factor_id, factor_version |
| 7. recon_S1_cat3 | Pure | `(anno, fuel)` | none | step, fuel, anno, sum_s1, cat3_csv, delta, delta_pct |
| 8. persist_emissions | Side | `ux_emissions_active_natural_key` in DB | 5× exp-backoff; if active-natural-key collision → emit correction via `fn_emit_correction` | step, rows_inserted_ar6, rows_inserted_ar5, correction_count |
| 9. mv_refresh | Side | one MV per tenant | 3× retry on lock timeout | step, mv_name, duration_ms |
| 10. close_batch | Side | `correlation_id` | retry 3× notification | step, run_duration_ms, crit_count, warn_count, info_count |

### 7.3 Idempotency keys (per data_quality_report §13.3)

```
Scope 1: (codice_sito | anno | combustibile | provenance)
Scope 2: (codice_sito | anno | voce_s2 | provenance)
Scope 3: (anno | categoria_s3 | sottocategoria | combustibile_or_blank)
Emission: (scope | sub_scope | codice_sito | anno | regulatory_stream | gwp_set)
```

Pre-insert: SELECT for `(idempotency_key, batch_id)` → if matched, skip + log DUPLICATE to DLQ.
At-insert: DB UNIQUE constraint guarantees no double-write under concurrency.

### 7.4 AR5 dual-track (FR-34 / MG-12) — parametrised single run, dual-write

**Decision (AD-004)**: a single ETL run takes a list `gwp_sets=[AR6, AR5]`. Steps 1–5 are GWP-agnostic (raw data is identical). Step 6 (factor_apply) executes calc modules **twice in-process**, once per GWP set, reading the same `ref.factor_catalog` rows (factors are GWP-agnostic) and the appropriate `ref.gwp_sets` table.

Step 8 dual-writes two rows per natural key:
- One with `regulatory_stream='CSRD_ESRS_E1'`, `gwp_set='AR6'` → consumed by CSRD PDF / dashboard
- One with `regulatory_stream='EU_ETS_PHASE_IV'`, `gwp_set='AR5'` → consumed by EU ETS export

Both rows share the same `correlation_id`. The `mv.mv_kpi_summary` keys on `(regulatory_stream, gwp_set)` so dashboard filters trivially.

Activity data (CO2 mass) is identical between the two — only CH4/N2O CO2e differ. The acceptance criterion for FR-34 ("CO2 values must be identical, only CH4/N2O CO2e differ by GWP") is enforced by a post-write integrity test in step 10 (`assert co2_tonne_AR6 == co2_tonne_AR5` for every natural key).

For Scope 1 process (decarbonation), CO2-only output is invariant across GWP sets (CO2 GWP = 1 in both). Stored with both `gwp_set` tags for traceability uniformity (MG-08).

### 7.5 DQ gate execution detail

| Gate | Step where fired | DLQ target | Block / annotate |
|---|---|---|---|
| MG-04 mandatory metadata NOT NULL (factor_source / factor_version / gwp_set / methodology) | 6 (factor_apply) — pre-emission write | DLQ + dq_findings (CRIT) | block emission row |
| DQ-CRIT-01..05 | 4 | DLQ + dq_findings (CRIT) | block pipeline (configurable per-rule) |
| DQ-WARN-01..08 | 4 | dq_findings (WARN) only | annotate; pipeline continues |
| FR-37-DEFAULT (Cat 3 metadata defaulting) | 3 (etl_synthesise) | dq_findings (INFO) per defaulted row | none (informational) |
| FR-11 Σ S1 reconciliation | 7 | dq_findings (INFO, delta=0 in current data) | none |
| MG-03 GO QC1..QC8 not all true | 6 (Scope 2 MB calc) | dq_findings (CRIT) | falls back to residual mix; row still written |

### 7.6 Provenance of the FR-01 / FR-02 synthesised zero rows

Synthesised rows in step 3 carry:

```json
{
  "provenance": "auto_zero_user_confirmed",
  "provenance_rationale": "<exact text from user 2026-05-13>",
  "fonte_dato": "ETL_synthesis",
  "qualita_dato": "U",
  "stato_dato": "Definitivo"
}
```

DQ-CRIT-05 gate explicitly tests `provenance != 'auto_zero_user_confirmed'` before firing.

---

## 8. Calculation Module Architecture (Phase 5 handover)

### 8.1 Common signature

Every per-scope calc module exposes a single `calculate` function with the same shape:

```python
# Conceptual signature — Phase 5 implements
def calculate(
    raw_rows: pd.DataFrame,
    factors: FactorCatalogPort,
    gwp: GWPSetTable,
    *,
    sigma_scope1: pd.DataFrame | None = None,   # for cat3 only (FR-11)
    correlation_id: UUID,
    created_by: str,
    regulatory_stream: str,                      # 'CSRD_ESRS_E1' or 'EU_ETS_PHASE_IV'
) -> list[EmissionRecord]:
    ...
```

- `factors: FactorCatalogPort` is the port interface — concrete impl in `infrastructure/persistence/factor_repo.py`.
- `gwp: GWPSetTable` is a frozen mapping; mixed-set call is impossible because the table is uniform per call (MG-10).
- All functions are pure: no DB writes, no network. The orchestrator in `application/services/calculation_service.py` persists the returned `EmissionRecord` list.

### 8.2 `EmissionRecord` dataclass — full metadata

Mirrors `calc.emissions_consolidated` schema (FR-22 / §10 of requirements.md):

```
EmissionRecord (frozen dataclass)
├── id: UUID            (generated server-side at persist time; for in-memory pre-persist = uuid4())
├── correlation_id: UUID
├── raw_row_id: UUID
├── raw_scope: int (1|2|3)
├── scope: int (1|2|3)
├── sub_scope: SubScope (Enum)
├── codice_sito: CodiceSito | None
├── anno: int
├── tco2e: Tco2e (Decimal(14,6))
├── co2_tonne: Decimal | None
├── ch4_tco2e: Decimal | None
├── n2o_tco2e: Decimal | None
├── factor_id: UUID            (FK to ref.factor_catalog.id)
├── factor_id_code: str        (denormalised "WTT_GAS_NAT_DEFRA_2025")
├── factor_version: str
├── factor_source: str
├── gwp_set: GWPSet ("AR6"|"AR5")
├── methodology: Methodology   (Enum)
├── regulatory_stream: str     ("CSRD_ESRS_E1"|"EU_ETS_PHASE_IV")
├── calc_timestamp: datetime (UTC)
├── created_by: str
├── valid_from: datetime
├── valid_to: datetime | None = None
├── superseded_by: UUID | None = None
├── reason_code: str | None = None
└── disclosure_notes: str | None = None
```

The class is immutable (`frozen=True`); any modification path raises `dataclasses.FrozenInstanceError` — first line of defence behind the DB trigger.

### 8.3 Per-module roles

| Module | requirement | Notes |
|---|---|---|
| `scope1_combustion.py` | FR-05 | GAS_NAT, GASOLIO, BENZINA; CO2 + CH4 + N2O components; DEFRA factors |
| `scope1_process.py` | FR-06 | IANO Processo_Decarb; CO2 only; factor `STOICH_CACO3_IPCC_2006` value 0.4397; `methodology='stoichiometric'`; `sub_scope='process'`; MG-08 / MG-09 |
| `scope1_fugitive_zero.py` | FR-35, MG-18 | Emits 7 zero-rows (one per site) with `sub_scope='fugitive'`, `methodology='declared-zero'`, `disclosure_notes=<OI-10 rationale>` |
| `scope2_lb.py` | FR-07 | All kWh × ISPRA Italian grid LB factor |
| `scope2_mb.py` | FR-08, MG-03 | For each (site, year) volume split: GO portion (`MB_GO_ZERO` factor) only if `v_go_certificate_qc_pass.all_qc_passed = TRUE` for the covering GO; otherwise residual mix (`MB_IT_RESIDUAL_AIB_2024`). MG-14 enforcement before write. |
| `scope3_cat1_purchased_goods.py` | FR-09 | Mass-based (ecoinvent) + spend-based (EXIOBASE); EPD override when registered |
| `scope3_cat2_capital_goods.py` | FR-10 | Spend-based EXIOBASE NACE C.27 / C.28 |
| `scope3_cat3_fuel_energy.py` | FR-11, MG-05 | **Input = `sigma_scope1` dataframe + Scope 2 totals — NOT cat3 CSV Quantità**. Cat3 CSV row used only for FR-11 reconciliation delta logging (currently 0). |
| `scope3_cat4_upstream_transport.py` | FR-12 | DEFRA road / rail / sea by mode; zero-tkm rows → explicit 0.0 |
| `scope3_cat5_waste.py` | FR-13 | DEFRA landfill / recycling; cut-off (no avoided emissions) |
| `scope3_cat6_business_travel.py` | FR-14 | DEFRA spend-based; EUR→GBP via PPP-adjusted rate; conversion docs in factor `applicability_note` |
| `scope3_cat7_commuting.py` | FR-15 | DEFRA average-car × 4,452,800 km (2024) / 4,259,200 km (2025); FTE annotated in disclosure_notes |
| `scope3_cat9_downstream_transport.py` | FR-16 | DEFRA HGV / sea; load factor 27t recorded in disclosure_notes |
| `scope3_cat11_zero_line.py` | FR-18, MG-06 | Emits 1 zero-line with `sub_scope='Cat11'`, `methodology='declared-zero'`, fixed rationale text |
| `scope3_cat12_eol.py` | FR-17 | 30%/70% split; ecoinvent v3.10; cut-off |
| `scope3_cat_omitted_zero_lines.py` | FR-36, MG-07 | Emits 5 zero-lines: Cat 8 / 10 / 13 / 14 / 15; per-category rationale text from methodology_validation §3.3 |

### 8.4 Calc orchestration sequence (calculation_service.py)

```
1. fugitive_zero    (FR-35)                    [scope 1]
2. scope1_combustion(FR-05)                    [scope 1]
3. scope1_process   (FR-06)                    [scope 1]
4. compute sigma_s1  (in-memory dataframe by (codice_sito, anno, fuel))
5. scope2_lb        (FR-07)                    [scope 2]
6. scope2_mb        (FR-08, MG-03 gate)        [scope 2]
7. compute sigma_s2  (kWh by year)
8. scope3_cat1..    (FR-09)                    [scope 3]
9. scope3_cat2      (FR-10)                    [scope 3]
10. scope3_cat3     (FR-11, input=sigma_s1+s2) [scope 3]
11. scope3_cat4     (FR-12)                    [scope 3]
12. scope3_cat5     (FR-13)                    [scope 3]
13. scope3_cat6     (FR-14)                    [scope 3]
14. scope3_cat7     (FR-15)                    [scope 3]
15. scope3_cat9     (FR-16)                    [scope 3]
16. scope3_cat12    (FR-17)                    [scope 3]
17. scope3_cat11_zero_line  (FR-18)            [scope 3]
18. scope3_cat_omitted_zero (FR-36)            [scope 3]
19. assemble + persist
```

Steps 1–18 are pure; step 19 is the only side-effectful op. Each step's output is a `list[EmissionRecord]` that is concatenated before persistence — making it trivial to run the whole pipeline twice for AR6/AR5 by varying `gwp` (AD-004).

### 8.5 Test coverage (NFR-15: 100% on calc)

- pytest + hypothesis property tests on `tco2e == sum(co2_tonne + ch4_tco2e + n2o_tco2e)` invariants per scope.
- Property test: any `EmissionRecord` derived from the AR5 GWP table must satisfy `co2_tonne_AR5 == co2_tonne_AR6` (CO2 invariant under GWP change).
- Golden-master tests against hand-computed expected `tco2e` values for representative rows in each calc module.

---

## 9. Dashboard (Streamlit) Layout

### 9.1 Pages

| Page | Purpose | requirement |
|---|---|---|
| `Home` | KPI cards: Scope 1 total, Scope 2 LB, Scope 2 MB, Scope 3 total, Total LB, Total MB, intensity tCO2e/t, tCO2e/M€, tCO2e/FTE; year selector; GWP set badge | FR-23, FR-25 |
| `1_DrillDown` | 5-level navigation Scope → Site → Category → Year → Subcategory; Plotly sunburst + table; tooltip exposes factor_source, factor_version, gwp_set, methodology | FR-23 |
| `2_YoY` | 2024 vs 2025 deltas per scope and category; persistent banner: "VIANO 2025 — reduced operation (real partial production halt)" sourced from `dq_findings.waiver_reason_code='OPERATIONAL_ANNOTATION'`; second banner: "VIANO_GARGOLA — gas commissioned 2025" | FR-24, DQ-WARN-01/06/07 resolution addendum |
| `3_Intensity` | tCO2e/t produced (KPI-09), tCO2e/M€ revenue (KPI-10), tCO2e/FTE (KPI-11, FTE 506→484 official HR); LB and MB variants side-by-side; reference-input fields for production tonnage & revenue persisted in `ref.reference_inputs` (table not shown above; trivial schema) | FR-25 |
| `4_FactorCatalog` | Read-only browser over `ref.factor_catalog`; filters by source / scope / category / vintage; click row → factor metadata page; download factor snapshot CSV | FR-04, MG-01 |
| `5_DQFindings` | Findings list filterable by severity / rule_id / site / year; counts dashboard (DQ-CRIT count = 0 expected post-Phase 3); waiver button (esg_manager only) writes a REMEDIATED finding with `parent_finding_id` | FR-32, KPI-13 |
| `6_AuditTrail` | Search and pagination over `mv.v_audit_trail`; expand row → raw row payload JSON + factor PDF link; export current view to Excel | FR-22 |

### 9.2 State management

- Single source of truth: a thin Streamlit "session bootstrapper" that on first run loads:
  - User JWT (from `st.experimental_user` or a login form bouncing to FastAPI `/auth/login`)
  - Tenant id (constant in v1)
  - Default gwp_set = 'AR6'
  - Default regulatory_stream = 'CSRD_ESRS_E1'
- **Shareable URLs**: filters (year, site, scope, gwp_set, regulatory_stream) persisted in `st.query_params` (read+write), not in `st.session_state`. Auditor link-sharing is then deterministic.
- **Caching** (`st.cache_data`):
  - `ref.factor_catalog` snapshot — TTL = 1h (factor publishes are infrequent)
  - `ref.sites`, `ref.gwp_sets` — TTL = 24h
  - `mv.mv_kpi_summary` slice — TTL = 60s (decouple from MV refresh latency)
  - `mv.v_audit_trail` slice — no cache (real-time audit)

### 9.3 Visual design

- Palette: **Okabe-Ito 8-colour** (NFR-22). Standardised CSS dict in `dashboard/components/palette.py`. Verified WCAG AA contrast for axis labels and tooltips.
- Plotly figures use `colorway = OKABE_ITO`. Bar/line/sunburst.
- Tooltip template includes: `factor_source · factor_version · gwp_set · methodology` (FR-23).

### 9.4 Localisation (IT/EN)

- Simple dict-lookup module `dashboard/i18n/{it,en}.json` keyed by canonical string IDs (`kpi.scope1.title`, `banner.viano_reduced_operation`, ...).
- Domain Italian terms (`Codice_Sito`, `Sm³`, `Gasolio`, `Quantità`) retained in both languages (FR-33).
- Language toggle in sidebar; persisted in `st.query_params`.
- PDF generation accepts a `lang=it|en` param (FR-28, FR-33).

---

## 10. PDF & Excel Generation

### 10.1 PDF (WeasyPrint — AD-006)

Tech choice rationale:
- ESRS E1-6 tables are inherently structured HTML tables; CSS gives full control over typography, page breaks, repeated table headers, ITF/Inter fonts.
- WeasyPrint is pure Python (no headless browser), works offline, supports `@page` rules for headers/footers, table of contents via CSS `target-counter`.
- ReportLab considered: more flexible but heavier template authoring; WeasyPrint wins on CSRD-table fidelity.

Template structure (HTML, located in `infrastructure/reporting/templates/`):

```
templates/
├── pdf_csrd/
│   ├── base.html                # Cover, header, footer, ToC
│   ├── _macros.html             # Currency, number, tCO2e formatters
│   ├── 00_cover.html            # Boundary, GWP set, base year, assurance level
│   ├── 01_scope1.html           # §44(a) Stationary + Mobile + Process + Fugitive zero
│   ├── 02_scope2.html           # §44(b) LB + MB; GO QC coverage rate
│   ├── 03_scope3.html           # §44(c) Cat 1..9, 12; Cat 11 + 8/10/13/14/15 zero rationales
│   ├── 04_intensity.html        # §45 KPI-09/10/11
│   ├── 05_methodology.html      # Factor catalog snapshot (factor_id, version, source, vintage)
│   └── 06_dq_disclosures.html   # DQ-WARN annotations (LOI, spend-based, proxy, fleet exp.)
└── pdf_csrd/styles/
    └── main.css                 # Okabe-Ito tokens, page rules, table styles
```

Header invariants (every page):
- `boundary = "Operational Control"`
- `gwp_set = "AR6"` (badge red if AR5 selected)
- `base_year = 2024`
- `assurance_level = "ISAE 3000 Limited"`
- `correlation_id` (small footer)

The same template engine, parameterised with `gwp_set='AR5'`, produces the AR5 EU ETS variant — header banner reads "EU ETS Phase IV — AR5" instead of CSRD. Output filename includes `gwp_set` to avoid confusion.

### 10.2 Excel (openpyxl — FR-27)

Sheet layout (every export is a self-contained audit pack):

| Sheet | Contents | Sheet protection |
|---|---|---|
| `01_Emissions_by_Scope` | Pivoted: rows = scope/sub_scope × year, columns = AR6/AR5; tCO2e values | locked, no edit |
| `02_Emissions_by_Site_Year` | rows = site × year, columns = scope sub-totals; intensity per FTE | locked |
| `03_Scope3_by_Category` | Cat 1..15, each row tagged status (IN / OMITTED / ZERO_LINE) and rationale | locked |
| `04_Audit_Trail` | One row per emission row: emission_id, raw_row_id, factor_id_code, factor_version, factor_source, gwp_set, methodology, calc_timestamp, valid_from, valid_to, superseded_by | locked |
| `05_Factor_Catalog_Snapshot` | Snapshot of ref.factor_catalog rows used in this run (joined to emission rows via factor_id) | locked |
| `06_DQ_Findings` | All findings for correlation_id, severity, resolution_status | locked |
| `07_GO_Certificate_Evidence` | One row per GO with QC1..QC8 booleans | locked |
| `08_Metadata` | run_id, correlation_id, gwp_set, regulatory_stream, etl_version, generated_by, generated_at, source_file_checksums | locked |

Sheet protection via `openpyxl.workbook.protection`. Password is **not** for confidentiality (file is exported to the user) but to prevent accidental in-place edits during auditor review.

### 10.3 Cross-cutting (PDF + Excel)

- Every artefact embeds `correlation_id` in metadata + footer.
- Every artefact embeds the **factor catalog snapshot** used (CG-04 / MG-01).
- For AR6 + AR5 runs, two separate files are produced; user can also request a combined Excel with two sets of computed sheets (toggle per request).

---

## 11. AR5 Dual-Track Implementation Detail (FR-34 / MG-12)

This section consolidates the AR5 design that touches multiple layers.

### 11.1 Storage layer
- `ref.gwp_sets` holds both AR6 and AR5 (with `valid_from` aligned to the IPCC publication dates).
- `calc.emissions_consolidated` has a NOT-NULL `gwp_set` column (`'AR6'` or `'AR5'`) plus `regulatory_stream`.
- Bitemporal natural-key index includes `gwp_set` so AR6 and AR5 rows for the same natural key coexist as separate active rows.

### 11.2 Pipeline layer
- ETL run is parameterised: `--gwp-sets AR6,AR5` (default both for IANO; AR6 only for non-EU-ETS sites if user later restricts).
- Step 6 calc loop iterates twice; step 8 dual-writes.
- Both writes share the same `correlation_id` and same `raw_row_id` — full auditor traceability across the two streams.

### 11.3 Reporting layer
- PDF and Excel templates select rows via `regulatory_stream` and `gwp_set` query params:
  - CSRD PDF: `regulatory_stream='CSRD_ESRS_E1' AND gwp_set='AR6'`
  - EU ETS export: `regulatory_stream='EU_ETS_PHASE_IV' AND gwp_set='AR5'`
- The EU ETS export is **tCO2e values + supporting metadata**; assembly into the MRR XML format is **out of v1 scope** (FR-34 acceptance). The ETS verifier consumes the Excel/JSON output, not an XML.

### 11.4 Integrity invariants (asserted by test in step 10)
- `count(rows AR6) == count(rows AR5)` per active natural key universe.
- `co2_tonne_AR6 == co2_tonne_AR5` for every paired natural key (only CH4/N2O CO2e differ).
- `factor_id` and `factor_version` are identical between paired rows (factors are GWP-agnostic except for the GWP table itself).
- `regulatory_stream` is mutually exclusive per row: a row in `EU_ETS_PHASE_IV` always has `gwp_set='AR5'`; a row in `CSRD_ESRS_E1` always has `gwp_set='AR6'`.

---

## 12. Observability & Logging

### 12.1 Structured logging (structlog → JSON to stdout)

Common log schema (every line):

```json
{
  "timestamp": "2026-05-13T14:35:21.123Z",
  "level": "INFO",
  "logger": "ghg_tool.etl.steps.persist_emissions",
  "correlation_id": "5f8d9e3a-7a8c-4c1e-8b1a-12c93f6b8a02",
  "user_id": "b2c3a4d5-...",
  "tenant_id": "<canonical-tenant-uuid>",
  "action": "calc.emit",
  "scope": 1,
  "sub_scope": "combustion",
  "codice_sito": "IANO",
  "anno": 2024,
  "resource": "calc.emissions_consolidated",
  "message": "Inserted 16 Scope-1 combustion rows",
  "duration_ms": 87
}
```

Fields never permitted: see PII redaction list in §6.4.

### 12.2 Health/readiness endpoints

- `GET /health` — returns 200 if the process is alive; no DB call.
- `GET /ready` — returns 200 only if: DB connection succeeds, `mv.mv_kpi_summary` refresh ≤ 24h old, MinIO PUT test succeeds.

### 12.3 Metrics (Prometheus client lib, `/metrics`)

Counters and histograms exposed:

| Metric | Type | Labels | Source |
|---|---|---|---|
| `etl_runs_total` | counter | `tenant_id`, `gwp_set`, `status=success|failed` | etl.pipeline |
| `etl_step_duration_ms` | histogram | `step` (0..10), `tenant_id` | etl.steps.* |
| `etl_dq_findings_total` | counter | `severity={CRIT,WARN,INFO}`, `rule_id` | etl.steps.dq_gates |
| `etl_dlq_rows_total` | counter | `severity`, `rule_id` | etl.steps.dq_gates |
| `api_requests_total` | counter | `method`, `route`, `status_code` | api.middleware |
| `api_request_duration_ms` | histogram | `route` | api.middleware |
| `auth_login_total` | counter | `outcome={success,failure}`, `reason` | api.routers.auth |
| `mv_refresh_duration_ms` | histogram | `mv_name` | etl.steps.mv_refresh |

Prometheus scraping infrastructure is **post-v1**; the `/metrics` endpoint is exposed now so it can be scraped immediately when ops adds it.

### 12.4 Tracing

OpenTelemetry SDK initialisation is wired but exporters are no-op in v1 (`OTEL_TRACES_EXPORTER=none`). All FastAPI routes and ETL steps already emit spans (via `opentelemetry.instrumentation.fastapi` and a manual `tracer.start_as_current_span` decorator on step functions). Ops can swap to OTLP exporter without code change.

---

## 13. Security Cross-Cutting Mapping

### 13.1 SG-01 .. SG-12 → architecture component

| SG | Mapped component | Mechanism |
|---|---|---|
| SG-01 | `infrastructure/security/jwt.py` + `api/dependencies/auth.py` | `python-jose.decode(..., algorithms=["RS256"])` whitelist; explicit `alg='none'` rejection test in CI |
| SG-02 | FastAPI middleware (`AuthMiddleware`) **+** PostgreSQL RLS (§5.3) | Two-layer denial; both are tested independently |
| SG-03 | RLS policies (§5.3) on every domain table; `tenant_id` GUC | `FORCE ROW LEVEL SECURITY`; future multi-tenant — no schema change needed |
| SG-04 | SQLAlchemy 2.x async with parameter binding; asyncpg | No `.execute(text(...))` with string concatenation; lint rule blocks raw `f"..."` SQL |
| SG-05 | pandera schemas (ETL) + Pydantic v2 models (API) | Bidirectional adapter `pandera.to_pydantic()` shared definitions where possible |
| SG-06 | Docker Compose reverse-proxy (nginx) terminating TLS 1.2+ in prod; HTTP → HTTPS redirect | Cert provisioning via Let's Encrypt in deploy manifest |
| SG-07 | `RequestLoggingMiddleware` + `structlog` processors; PII regex denylist (§6.4) | Drop fields by name; mask by regex |
| SG-08 | GitHub Actions step `gitleaks` (NFR-25); `.gitleaks.toml` with custom rules for ISPRA/DEFRA tokens | Block merge on findings |
| SG-09 | GitHub Actions step `bandit -ll`; HIGH severity blocks | CI required check |
| SG-10 | `slowapi` middleware backed by Redis | 100 req/min/user authenticated; `Retry-After` header on 429 |
| SG-11 | `Dockerfile` `FROM python:3.11-slim@sha256:<digest>` (digest-pinned); Renovate/Dependabot on base + deps | Reproducible builds; CVE scanning by Trivy in CI |
| SG-12 | RBAC role separation (§5.1) + RLS (§5.3) + explicit endpoint role gates: `Depends(require_role("esg_manager"))` on `/reports/pdf` and `/emissions/corrections`; `Depends(require_role("data_steward"))` on `/emissions` POST and `/factor-catalog` POST | Tested in CI integration tests |

### 13.2 GDPR (CG-01 / CG-02 / NFR-20)

- **Art. 30 register** lives in `docs/gdpr_processing_register.md` (Phase 9 output of documentation-agent), not in code; the data items processed by this tool that constitute personal data are: `ref.users.{username, email}` (employee identifiers of system users — not data subjects of GHG accounting); commuting Cat 7 uses **aggregate FTE counts**, no individual employee linkage.
- **DPIA**: not required for v1 since no individual-level employee data is stored. If a future enhancement introduces per-employee commuting tracking (km per employee), a DPIA is triggered and CG-02 becomes active.
- PII at rest: `ref.users.password_hash` is bcrypt-hashed; columns containing email are not encrypted at column level but the DB is encrypted at rest at the volume layer (Docker volume / managed PG TDE).

### 13.3 Retention (NFR-19, CG-05)

- Emissions retained ≥10 years from reporting year (CSRD Art. 19a).
- No `ON DELETE CASCADE` on any path touching `calc.emissions_consolidated`, `calc.audit_log`, `calc.dq_findings`, `calc.dlq`.
- Backup policy operationalised by IT Operations (out of scope here): daily pg_basebackup + WAL archiving to MinIO; quarterly restore test.

---

## 14. Deployment & CI/CD

### 14.1 Local development — Docker Compose

`docker-compose.dev.yml` services:

```
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB:       ghg_tool
      POSTGRES_USER:     app_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}   # from .env
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app_user -d ghg_tool"]
      interval: 5s
      retries: 12

  minio:
    image: minio/minio:RELEASE.2025-XX-XX     # digest-pinned in prod
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER:     ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes:
      - miniodata:/data

  redis:
    image: redis:7-alpine

  fastapi:
    build:
      context: .
      target: api
    depends_on:
      postgres: { condition: service_healthy }
      minio:    { condition: service_started }
      redis:    { condition: service_started }
    environment:
      DATABASE_URL:    postgresql+asyncpg://app_user:${POSTGRES_PASSWORD}@postgres/ghg_tool
      JWT_SECRET:      ${JWT_SECRET}
      JWT_ALG:         RS256
      MINIO_ENDPOINT:  minio:9000
      REDIS_URL:       redis://redis:6379/0
    ports: ["8000:8000"]
    command: >
      sh -c "alembic upgrade head &&
             uvicorn ghg_tool.api.main:app --host 0.0.0.0 --port 8000"

  streamlit:
    build:
      context: .
      target: dashboard
    depends_on:
      fastapi: { condition: service_started }
    environment:
      API_BASE_URL: http://fastapi:8000
    ports: ["8501:8501"]
    command: >
      streamlit run src/ghg_tool/dashboard/Home.py
        --server.port 8501 --server.address 0.0.0.0

  etl:
    build:
      context: .
      target: etl
    depends_on:
      postgres: { condition: service_healthy }
    profiles: ["etl-manual"]                  # not started on `up`; run on demand
    command: >
      python -m ghg_tool.etl.pipeline
        --raw-dir /data/raw
        --gwp-sets AR6,AR5
        --triggered-by ${USER:-data_steward}

volumes:
  pgdata: {}
  miniodata: {}
```

Goal for NFR-24: `docker compose up` produces a working stack in < 5 min on a clean laptop.

### 14.2 Production deployment

- Same Compose file in production with prod overrides (`docker-compose.prod.yml`): TLS terminator (nginx or Traefik), digest-pinned images, healthchecks tightened, no auto-migrate.
- Migrations in prod are **manual**: `docker exec fastapi alembic upgrade head` run from a release runbook, recorded in audit_log.

### 14.3 Dockerfile (multi-stage)

```
# syntax=docker/dockerfile:1.7
# Stage 1: deps
FROM python:3.11-slim@sha256:<digest> AS deps
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Stage 2: builder (compile pandas wheels etc, install dev deps)
FROM deps AS builder
RUN uv sync --frozen
COPY src ./src
COPY tests ./tests

# Stage 3: api
FROM deps AS api
COPY src ./src
USER 10001:10001
EXPOSE 8000
HEALTHCHECK CMD curl -fsS http://localhost:8000/ready || exit 1

# Stage 4: dashboard
FROM deps AS dashboard
COPY src ./src
USER 10001:10001
EXPOSE 8501

# Stage 5: etl
FROM deps AS etl
COPY src ./src
COPY data ./data
USER 10001:10001
ENTRYPOINT ["python", "-m", "ghg_tool.etl.pipeline"]
```

### 14.4 GitHub Actions (`.github/workflows/ci.yml`)

```
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install uv && uv sync --frozen
      - run: uv run ruff check src tests
      - run: uv run ruff format --check src tests
      - run: uv run mypy --strict src
      - run: uv run import-linter             # AD-001 layered policy

  test:
    needs: lint
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install uv && uv sync --frozen
      - run: uv run alembic upgrade head
      - run: uv run pytest --cov=ghg_tool --cov-fail-under=85
      - run: uv run pytest tests/calc --cov=ghg_tool.application.calc --cov-fail-under=100
      - run: uv run pytest tests/integration -k "rls or immutability"
      # ↑ enforces CG-03 (deny_update_delete trigger) and SG-02/03

  security:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install bandit && bandit -r src -ll
      - uses: aquasecurity/trivy-action@master
        with: { scan-type: fs, severity: "CRITICAL,HIGH", exit-code: "1" }

  build:
    needs: [test, security]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    permissions: { contents: read, packages: write }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
      - run: |
          for target in api dashboard etl; do
            docker buildx build --target $target -t ghcr.io/${{ github.repository }}/$target:${{ github.sha }} --push .
          done
```

Secrets (JWT_SECRET, POSTGRES_PASSWORD, MINIO creds) sourced from GitHub Actions Secrets; not committed.

---

## 15. Methodological Gates Mapping (MG-01 .. MG-18)

| Gate | Where enforced | Mechanism |
|---|---|---|
| **MG-01** Factor catalog seeded per §11 (38 rows) with required columns | `ref.factor_catalog` + Alembic seed in M2 | Schema NOT NULL constraints (§4.2); Phase 5 seed script populates 38 entries (with `is_licence_only=TRUE` for ecoinvent/EXIOBASE) |
| **MG-02** Factor catalog immutable post-publish | `ops.deny_factor_mutation()` trigger (§4.2) | UPDATE/DELETE blocked when `is_published=TRUE`; tested in CI |
| **MG-03** Scope 2 MB `MB_GO_ZERO` gated by per-cert QC1..QC8 | `scope2_mb.py` reads `ref.v_go_certificate_qc_pass`; only assigns MB=0 to volume covered by certs with `all_qc_passed=TRUE`; otherwise residual mix | Calc module + view; result tested |
| **MG-04** Mandatory metadata NOT NULL on every emission row | DB CHECK constraint `chk_metadata_nonnull` on `calc.emissions_consolidated` (§4.3) + Pydantic v2 model on API | Reject pre-insert in app; fail-safe at DB |
| **MG-05** Cat 3 WTT uses Σ Scope 1 (not CSV Cat 3 Quantità) | `scope3_cat3_fuel_energy.py` signature takes `sigma_scope1`; calc orchestrator computes it from raw S1 frame; CSV delta logged to `dq_findings` (currently 0) | Calc module + orchestrator step 4 |
| **MG-06** Cat 11 zero-line auto-emitted with rationale | `scope3_cat11_zero_line.py` → emits one row per run with fixed `disclosure_notes` text | Calc module; CI test asserts presence |
| **MG-07** Cat 8/10/13/14/15 zero-lines with rationale | `scope3_cat_omitted_zero_lines.py` → emits 5 rows | Calc module; CI test asserts presence |
| **MG-08** IANO Processo_Decarb: `factor_id='STOICH_CACO3_IPCC_2006'`, `methodology='stoichiometric'`, `sub_scope='process'`, CO2-only | `scope1_process.py` constants; assertion in module | Calc module; property test |
| **MG-09** LOI-3.5% methodology and ±10–20% uncertainty annotated | `scope1_process.py` sets `disclosure_notes`; PDF template `01_scope1.html` renders annotation | Calc + reporting |
| **MG-10** Mixed-GWP-set runs rejected | `domain.policies.gwp_enforcement.GWPSetTable` is a frozen mapping per call; `FR-19` rejected in `ingestion_service` if requested `gwp_sets` are not all members of `{AR6,AR5}` | Domain policy |
| **MG-11** Dashboard / Excel / PDF disclose `gwp_set` in header | Streamlit page header component reads `gwp_set` from query params; Excel sheet `08_Metadata`; PDF cover `00_cover.html` includes `{{ gwp_set }}` | Reporting |
| **MG-12** AR5 dual-track wired (OI-7 YES) | ETL --gwp-sets AR6,AR5 default for IANO; dual-write in step 8 (§7.4, §11) | ETL + storage; integrity test in step 10 |
| **MG-13** Cat 15 OMIT zero-line auto-emitted (OI-8 NO) | Same module as MG-07 (`scope3_cat_omitted_zero_lines.py`) | Calc module |
| **MG-14** GO QC1..QC8 checklist completed before MB=0 publication | App-layer check in `scope2_mb.py`; database view `ref.v_go_certificate_qc_pass` aggregates the 8 booleans; covered volume splitter | Calc + view |
| **MG-15** AIB Italian residual mix 2024 numeric pinned | `ref.factor_catalog` row `MB_IT_RESIDUAL_AIB_2024` with non-NULL `value` and `pdf_source_uri` referencing the AIB PDF in MinIO | Phase 5 data-engineer task; CI lint asserts the row is not LICENCE-only and has a value |
| **MG-16** ISPRA LB factor pinned (FY2024 or FY2023+offset) | `ref.factor_catalog` row `LB_IT_GRID_ISPRA_2024` with `value` and `applicability_note` documenting offset | Phase 5 data-engineer; CI lint |
| **MG-17** DEFRA 2025 (or 2026) edition pinned for WTT/freight/travel/waste | All DEFRA-sourced rows in `ref.factor_catalog` have `version` and `vintage` populated | Phase 5; CI lint |
| **MG-18** Scope 1 Fugitive HFC zero-line auto-emitted (OI-10) | `scope1_fugitive_zero.py` → 7 rows (one per site) with `sub_scope='fugitive'`, `methodology='declared-zero'`, fixed rationale | Calc module; CI test |

---

## 16. Open Architectural Decisions (ADR seeds for Phase 5)

These are decisions the architect cannot finalise without implementation experiments in Phase 5. Each is structured as an ADR seed.

### ADR-001 — Pandas vs Polars for ETL

- **Status**: Proposed (pandas)
- **Context**: NFR-01 budget is 10 min wall-clock; v1 dataset is tiny (~150 rows); pandera supports both but pandas has the longest track record.
- **Decision (provisional)**: pandas for v1.
- **Reassess if**: any single ETL step exceeds 30s on the reference dataset, or if a future ingestion path (ERP feed via FR-30) introduces 100k+ rows.
- **Migration path**: calc modules signature `pd.DataFrame` is the only coupling; switching to polars requires `to_pandas()` shim on persist boundary OR a generic `DataFrame` Protocol.

### ADR-002 — WeasyPrint vs ReportLab for PDF

- **Status**: Proposed (WeasyPrint)
- **Context**: CSRD tables align well with HTML/CSS.
- **Reassess if**: PDF generation exceeds NFR-03 budget (< 60s), or font rendering on Italian-language pages introduces unacceptable artefacts.
- **Migration path**: keep the calc/data-prep layer untouched; only `infrastructure/reporting/pdf_*.py` adapter changes.

### ADR-003 — ETL retry/backoff numerics

- **Status**: Proposed (5 retries, exp 0.5/1/2/4/8 s)
- **Context**: section 7.2 baseline.
- **Reassess if**: production telemetry shows DB blip patterns where these numbers are too aggressive or too lenient.

### ADR-004 — Materialized view refresh strategy

- **Status**: Proposed (`REFRESH CONCURRENTLY` post-ETL only)
- **Reassess if**: dashboard cold-start exceeds NFR-02 (< 5s), or if intra-day reads need staleness < 60s.
- **Migration path**: pg_cron or a Streamlit-triggered refresh button for esg_manager.

### ADR-005 — Multi-tenant evolution path

- **Status**: Single-tenant v1 with `tenant_id` schema (AD-007).
- **Reassess if**: customer base grows to ≥2 tenants. At that point, decide schema-per-tenant vs RLS-based row isolation (RLS infrastructure already in place — should be a low-effort jump).

### ADR-006 — Choice of authoritative ISPRA factor vintage

- **Status**: Open — depends on data-engineer's Phase 5 fetch.
- **Decision rule**: If ISPRA 2024 vintage is published before Phase 5 cut-off, use it; otherwise FY2023 + documented offset (MG-16).

### ADR-007 — Biogenic CO2 disclosure schema (OI-9)

- **Status**: Open — methodology requires the policy choice (OI-9 in methodology_validation.md §10.2).
- **Likely shape**: add two nullable columns `co2_biogenic_tonne` and `co2_fossil_tonne` to `calc.emissions_consolidated` and ESRS E1-7 disclosure section in PDF.
- **Resolution required by**: ESRS E1-6 PDF sign-off for FY2024.

### ADR-008 — Factor pinning automation (OI-5 closure)

- **Status**: Open — methodology_validation.md §4.5.
- **Question**: should the factor catalog be seeded by a one-time SQL fixture or by a Phase 5 Python script that retrieves URLs (DEFRA, ISPRA, AIB) and writes hash-pinned PDFs to MinIO?
- **Recommendation**: Python seeding script — provides auditable provenance.

---

## 17. Tools & Libraries — Pinned (proposed `pyproject.toml` snippet)

```toml
[project]
name = "ghg-tool"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
    # API
    "fastapi==0.115.*",
    "uvicorn[standard]==0.32.*",
    "python-jose[cryptography]==3.3.*",
    "bcrypt==4.2.*",
    "slowapi==0.1.*",

    # Validation
    "pydantic==2.9.*",
    "pydantic-settings==2.6.*",
    "pandera==0.20.*",

    # ETL / data
    "pandas==2.2.*",
    # "polars==1.13.*",                # deferred per ADR-001

    # Persistence
    "sqlalchemy==2.0.*",
    "asyncpg==0.30.*",
    "alembic==1.13.*",

    # Reporting
    "weasyprint==62.*",
    "openpyxl==3.1.*",
    "jinja2==3.1.*",

    # Object store
    "minio==7.2.*",

    # Dashboard
    "streamlit==1.39.*",
    "plotly==5.24.*",

    # Observability
    "structlog==24.4.*",
    "prometheus-client==0.21.*",
    "opentelemetry-api==1.27.*",
    "opentelemetry-instrumentation-fastapi==0.48*",

    # Misc
    "httpx==0.27.*",                      # API client used by Streamlit
    "tenacity==9.0.*",                    # retry/backoff
    "ulid-py==1.1.*",                     # secondary ID for log correlation
]

[project.optional-dependencies]
dev = [
    "pytest==8.3.*",
    "pytest-asyncio==0.24.*",
    "pytest-cov==5.0.*",
    "hypothesis==6.115.*",
    "ruff==0.7.*",
    "mypy==1.13.*",
    "import-linter==2.1.*",
    "bandit==1.7.*",
    "gitleaks==8.21.*",            # via pre-commit if not via Action
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.mypy]
strict = true
python_version = "3.11"
plugins = ["pydantic.mypy", "sqlalchemy.ext.mypy.plugin"]

[tool.import-linter]
root_packages = ["ghg_tool"]

[[tool.import-linter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
    "ghg_tool.api",
    "ghg_tool.dashboard",
    "ghg_tool.etl",
    "ghg_tool.application",
    "ghg_tool.infrastructure",
    "ghg_tool.domain",
]
ignore_imports = [
    # api/dashboard/etl all may touch infrastructure for DI wiring only in main.py
    "ghg_tool.api.main -> ghg_tool.infrastructure",
    "ghg_tool.etl.pipeline -> ghg_tool.infrastructure",
    "ghg_tool.dashboard.* -> ghg_tool.infrastructure",
]
```

### 17.1 Version-pinning policy

- **Minor + patch** versions floated via `==X.Y.*` to allow security patches without code change.
- **Renovate / Dependabot** opens PRs for minor bumps; PRs gated by the full CI pipeline.
- Major bumps require an explicit ADR (e.g. SQLAlchemy 3, Pydantic 3) — never auto-merged.
- All transitive deps pinned in `uv.lock` / `poetry.lock`, committed to version control.

---

## 18. Coverage Confirmation — FRs / NFRs / MGs / CGs / SGs

### 18.1 Functional Requirements

| FR | Component(s) |
|---|---|
| FR-01, FR-02, FR-03 | ETL §7.1–§7.3 step 1+2+5; raw staging schema §4.1; pandera schemas in `infrastructure/ingestion/pandera_schemas.py` |
| FR-04 | `ref.factor_catalog` §4.2; MG-01/02 mapping §15 |
| FR-05 | `application.calc.scope1_combustion` §8.3 |
| FR-06 | `application.calc.scope1_process` §8.3; MG-08/09 |
| FR-07, FR-08 | `application.calc.scope2_lb` / `scope2_mb` §8.3; MG-03/14 |
| FR-09..FR-17 | per-category calc modules §8.3 |
| FR-18 | `scope3_cat11_zero_line` §8.3; MG-06; PDF template `03_scope3.html` |
| FR-19 | `domain.policies.gwp_enforcement` §3.1; MG-10 |
| FR-20 | `calc.emissions_consolidated` immutability §4.3; CG-03 |
| FR-21 | `calc.fn_emit_correction` stored procedure §4.3; correction_service §3.1 |
| FR-22 | `correlation_id` propagation §6.3 middleware; `mv.v_audit_trail` view §4.4 |
| FR-23 | Streamlit `1_DrillDown` page §9.1 |
| FR-24 | Streamlit `2_YoY` page §9.1 (VIANO banner) |
| FR-25 | Streamlit `3_Intensity` page §9.1 |
| FR-26 | `correction_service` + comparison logic; triggers `RESTATEMENT_>5PCT` reason_code |
| FR-27 | Excel generator `infrastructure/reporting/excel_openpyxl.py`; layout §10.2 |
| FR-28 | WeasyPrint PDF generator §10.1 |
| FR-29 | FastAPI GET routers §6.1 |
| FR-30 | FastAPI POST `/emissions` §6.2.2 |
| FR-31 | RBAC §5; RLS §5.3; JWT §5.5 |
| FR-32 | DQ gates in ETL step 4 §7.5; `calc.dq_findings` + `calc.dlq` §4.3 |
| FR-33 | Streamlit i18n §9.4; PDF lang param §10.1 |
| FR-34 | AR5 dual-track §11; MG-12 |
| FR-35 | `scope1_fugitive_zero` §8.3; MG-18 |
| FR-36 | `scope3_cat_omitted_zero_lines` §8.3; MG-07 / MG-13 |
| FR-37 | ETL step 3 default-fill §7.2; raw schema `metadata_defaulted` flag §4.1 |

### 18.2 Non-Functional Requirements

| NFR | Component(s) |
|---|---|
| NFR-01 | ETL pipeline §7 — pandas chosen for headroom; ADR-001 reassess gate |
| NFR-02 | `mv.mv_kpi_summary` §4.4; Streamlit cache §9.2 |
| NFR-03 | WeasyPrint §10.1 — 60s budget; ADR-002 reassess |
| NFR-04 | openpyxl §10.2 — 30s budget |
| NFR-05 | JWT design §5.5 (HS256/RS256, 1h access, 24h refresh) |
| NFR-06 | RBAC middleware + RLS §5 |
| NFR-07 | pandera (ETL) + Pydantic v2 (API) §13.1 SG-05 |
| NFR-08 | PII redaction §6.4 |
| NFR-09 | SG-01..SG-12 mapping §13 |
| NFR-10 | TLS terminator §13 SG-06; nginx in compose §14 |
| NFR-11 | slowapi + Redis §6.3 |
| NFR-12 | Idempotency keys §7.3; UNIQUE constraints §4.1 |
| NFR-13 | `calc.dlq` §4.3 + replay endpoint (data_steward) §6.1 |
| NFR-14 | `deny_emissions_mutation` trigger §4.3; CI test §14.4 |
| NFR-15 | Test coverage gates §14.4 (85% global / 100% calc) |
| NFR-16 | ruff config + flake8-cognitive-complexity in CI |
| NFR-17 | Python 3.11+ pinned in §17 pyproject |
| NFR-18 | `raw_row_id` + `raw_scope` FK semantics §4.3 |
| NFR-19 | Retention via no-cascade design §13.3 |
| NFR-20 | GDPR Art. 30 register doc §13.2; CG-01 |
| NFR-21 | Trigger §4.3; tested in CI |
| NFR-22 | Okabe-Ito palette §9.3 |
| NFR-23 | i18n module §9.4 |
| NFR-24 | Docker Compose §14.1 |
| NFR-25 | GitHub Actions pipeline §14.4 |

### 18.3 Compliance Gates (CG-01..CG-11)

| CG | Component(s) |
|---|---|
| CG-01 GDPR Art. 30 | `docs/gdpr_processing_register.md` (Phase 9 doc); §13.2 |
| CG-02 DPIA | Not triggered v1 §13.2 |
| CG-03 Trigger tested in CI | `tests/integration/test_immutability.py` §14.4 |
| CG-04 Metadata NOT NULL | DB CHECK constraint §4.3; MG-04 |
| CG-05 10-year retention | §13.3 |
| CG-06 ESRS E1-6 data points | PDF templates §10.1 |
| CG-07 Cat 11 zero-line | MG-06 / FR-18 §8.3 |
| CG-08 GO QC validation | §4.2 + MG-03/14 §15 |
| CG-09 GWP set documented | MG-11 §15 |
| CG-10 EU Taxonomy placeholder | PDF template `06_dq_disclosures.html` includes the placeholder line |
| CG-11 ISAE 3000 scope agreed | Process doc (Phase 9); not architectural |

### 18.4 Security Gates (SG-01..SG-12)

Fully mapped in §13.1.

---

## 19. References

The architecture is grounded in the following documents:

1. `/home/user/ghg-tool/docs/requirements.md` v1.2.1 (APPROVED 2026-05-13) — 37 FRs, 25 NFRs, 11 CGs, 12 SGs, traceability matrix.
2. `/home/user/ghg-tool/docs/methodology_validation.md` v1.0.0 (2026-05-13) — §11 factor catalog seed (38 rows), §12 methodological gates (MG-01..MG-18), §2.4 GO QC checklist, §6.2 stoichiometric derivation.
3. `/home/user/ghg-tool/docs/data_quality_report.md` v1.0.0 (2026-05-13) — §13.1 DLQ schema, §13.2 dq_findings schema, §13.3 idempotency keys, §13.4 provenance flag, §13.5 schema note, §14 resolution addendum (Phase 5 unblock).

Normative external sources cited via methodology_validation §13: GHG Protocol Corporate Standard, Scope 2 Guidance, Scope 3 Standard; IPCC AR6 / AR5; CSRD ESRS E1 (Delegated Regulation 2023/2772); EU ETS MRR (Regulations 2018/2066, 2023/2122); D.Lgs. 199/2021 (Italian GO regime); ISPRA Rapporto 386/2023 + 413/2025; AIB European Residual Mix 2024; DEFRA / DESNZ 2025; ecoinvent v3.10; EXIOBASE v3.x; ISO 14064-1:2018; ISO 21930:2017; ISO 14067.

---

*End of Document — Version 1.0.0 — 2026-05-13 — ISSUED. Ready for Phase 5 (data-engineer, backend-engineer, visualization-engineer, calc-developer) handover. Reviewer-agent and compliance-agent sign-off to follow in Phase 8.*
