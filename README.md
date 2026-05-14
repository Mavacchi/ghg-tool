# GHG Accounting Tool — Ceramic Tile Manufacturer

![Build](https://img.shields.io/badge/build-passing-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-95%25%2B-brightgreen)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-FF4B4B)
![License](https://img.shields.io/badge/license-proprietary-lightgrey)

Purpose-built GHG emissions accounting system for Saturnia Ceramica S.r.l., a gres
porcellanato manufacturer operating 7 Italian production sites. The platform ingests annual
activity data, applies a versioned emission factor catalog, calculates greenhouse gas
emissions across Scopes 1, 2, and 3 per the GHG Protocol Corporate Standard, and produces
CSRD-grade outputs designed to support ESRS E1 disclosure obligations and EU ETS Phase IV
reporting for the IANO Annex I Activity 17 installation.

Phase 9 (documentation) complete: 540 tests passing, mypy --strict on 149 source files,
coverage >= 95%. Security APPROVED. Compliance APPROVED.

---

## Install

```bash
# 1. Clone and create virtual environment
git clone <repo-url> ghg-tool && cd ghg-tool
python3.11 -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
make install

# 3. Start PostgreSQL 15 via Docker Compose
make db-up

# 4. Run all Alembic migrations (M0 through M7)
make migrate

# 5. Run linting and tests
make lint
make test
```

---

## Quickstart

```bash
# Start the database (if not already running)
docker compose up -d db

# Apply all migrations
alembic upgrade head

# Start the FastAPI API server (port 8000)
uvicorn ghg_tool.api.main:app --host 0.0.0.0 --port 8000

# In a separate terminal, start the Streamlit dashboard (port 8501)
streamlit run src/ghg_tool/ui/streamlit_app/Home.py
```

After the ETL pipeline runs (`make etl`), the dashboard at `http://localhost:8501` provides
scope-to-subcategory drill-down, year-over-year comparison (2024 vs 2025), and intensity
metrics (tCO2e/tonne, tCO2e/M EUR, tCO2e/FTE).

The API is documented at `http://localhost:8000/docs` (OpenAPI 3.1).

---

## Architecture Overview

Hexagonal / ports-and-adapters design. Calculation logic lives in `domain/` with no
framework imports; infrastructure adapters in `infrastructure/`; FastAPI in `api/`;
Streamlit in `ui/`.

```
src/ghg_tool/
  domain/          Pure Python domain models and calculation logic
  application/     Use cases: ETL orchestration, calculation services, export services
  infrastructure/  DB adapters (SQLAlchemy 2.x), factor loader, JWT security
  api/             FastAPI application, routers, middleware, RBAC
  ui/              Streamlit pages, PDF templates (WeasyPrint), Excel sheets (openpyxl)
  etl/             ETL pipeline stages and pandera validation schemas
```

Database schemas: `raw` (ingestion staging), `ref` (users, roles, factor catalog),
`calc` (emissions, DQ findings, DLQ, audit log), `ops` (shared mutation-guard functions).

See `docs/architecture.md` for the full C4 diagram, DDL, and RBAC/RLS design.

---

## ESG Methodology

The calculation methodology implements:

- **GHG Protocol Corporate Standard (2004)** — organisational boundary (operational control),
  Scope 1/2/3 definitions, dual Scope 2 reporting (LB + MB)
- **GHG Protocol Scope 2 Guidance (2015)** — 8 Quality Criteria for Guarantees of Origin
- **GHG Protocol Corporate Value Chain (Scope 3) Standard (2011)** — 9 material categories
- **CSRD ESRS E1** — disclosure data points E1-6 §44/§45; E1-7 biogenic carbon
- **IPCC AR6 GWP100** (CH4=27.9, N2O=273) — primary GWP set; AR5 maintained for EU ETS
- **EU ETS Phase IV** (Directive 2003/87/EC; MRR 2018/2066) — AR5 dual-track for IANO

Biogenic CO2 is stored in a separate column (`co2_biogenic_tonne`) and is never summed
into Scope 1/2/3 totals, per GHG Protocol §4.5 and ESRS E1-7.

All emission records are append-only with bitemporal versioning. Corrections follow a
stored-procedure workflow with 5 canonical reason codes. No UPDATE or DELETE is permitted
on the emission tables.

See `docs/methodology.md` for the full methodology reference.

---

## Compliance Posture

This tool is designed to support the following obligations. No certification is claimed;
the operator is responsible for regulatory filings.

| Framework | Status | Notes |
|---|---|---|
| CSRD / ESRS E1 | Supported — designed to support Art. 19a obligations | ESRS E1-6 tables, E1-7 biogenic; ISAE 3000 Limited assurance package (audit trail, factor provenance, immutability proof) |
| GRI 305: Emissions | Supplemental alignment | GRI 305-1/305-2/305-3/305-4 data points present |
| EU ETS Phase IV | AR5 dual-track output for IANO (Annex I Activity 17) | MRR XML format deferred to v2 |
| ISO 14064-1:2018 | Reference alignment | Consistent with GHG Protocol; cited in assurance package |
| GDPR Art. 6/Art. 30 | Records of processing activities maintained | See `docs/gdpr_processing_register.md` |
| EU Taxonomy (Regulation 2020/852) | Out of scope v1; placeholder disclosure in PDF | Assessment deferred to v2 |
| SFDR PAI indicators | Out of scope | Issuer-level tool; not a financial-market participant |

Security posture: JWT HS256 (>= 32-char secret enforced at startup), bcrypt-12 password
hashing, PostgreSQL RLS on all emission tables, security-barrier views on materialised
views (M7), append-only audit trail with deny-mutation trigger (M1), PII-free structured
logging (usernames SHA-256 hashed), 5/min login rate limit.

See `docs/gdpr_processing_register.md` and `docs/deployment.md` for production guidance.

---

## Deployment

See `docs/deployment.md` for the full production runbook, including:
- Environment variable reference (GHG_JWT_SECRET, GHG_ENVIRONMENT, DATABASE_URL, etc.)
- Alembic migration sequence and grant verification
- TLS termination requirements (reverse proxy mandatory)
- Acknowledged risk register (SEC-ADV-008 in-process rate limiter, SEC-ADV-009 CORS
  credentials, SEC-ADV-010 CSP and Streamlit) with operator actions
- Backup / restore procedure including the immutable audit log restoration protocol
- Smoke test checklist (login, /kpis, /intensity, PDF export with magic-bytes check)

---

## Roadmap

See `docs/roadmap.md` for deferred items:

- **v1.1**: Celery migration for export service (REV-WAVE3-007), factor string constants
  (REV-WAVE3-010), biogenic memo refactor (REV-WAVE3-018)
- **v2 hardening**: PyJWT migration from python-jose (SEC-P1-004, CVE-2024-33664),
  refresh token rotation with Redis blacklist (SEC-P1-007), Redis-backed rate limiter
  (SEC-ADV-008)
- **v2 features**: EU ETS MRR XML, EU Taxonomy KPIs, SFDR PAI indicators,
  Scope 3 Hot Spot Analysis, multi-tenant admin panel

---

## Development

```bash
make lint          # ruff + mypy --strict (149 source files, zero errors)
make test          # pytest unit + property tests (540 passing)
make test-integration  # requires make db-up first; integration tests with live DB
make coverage      # pytest --cov with HTML report; threshold >= 95%
```

CI pipeline (GitHub Actions): lint -> mypy -> pytest -> coverage -> bandit -> gitleaks.
All checks are required gates on every PR.

---

## License and Contact

Proprietary — Saturnia Ceramica S.r.l. All rights reserved.

For questions about this tool: [TBD — insert internal contact before deployment]
For data protection enquiries: [TBD — insert DPO contact before deployment]
