# GHG Accounting Tool — Ceramic Tile Manufacturer

Purpose-built GHG emissions accounting system for a gres porcellanato manufacturer operating 7 Italian production sites. Covers Scopes 1, 2, and 3 per the GHG Protocol Corporate Standard, targets CSRD ESRS E1 disclosure, and produces the EU ETS Phase IV AR5 dual-track output for IANO (Annex I Activity 17).

**Documentation** lives in `docs/`:
- `docs/requirements.md` — v1.2.1 APPROVED, 37 FRs, 25 NFRs
- `docs/methodology_validation.md` — v1.0.0, OI-7/OI-9/OI-10 closed
- `docs/data_quality_report.md` — v1.0.0 + §14 addendum, all DQ-CRIT closed
- `docs/architecture.md` — v1.0.0, DDL, RBAC/RLS, ETL DAG

Phase 9 (documentation-agent) will expand this file with full operational runbooks.

## Quick start

```bash
make install      # install dev dependencies into .venv
make db-up        # start PostgreSQL 15 + MinIO via Docker Compose
make migrate      # run Alembic migrations (M0 → M5)
make etl          # run the ETL pipeline against data/raw/
make test         # unit tests (integration tests require make db-up first)
make lint         # ruff + mypy
```

## Architecture overview

Hexagonal / ports-and-adapters layering:

```
src/ghg_tool/
├── domain/          # Pure Python — no framework imports
├── application/     # Use cases (calc modules, services)
├── infrastructure/  # DB adapters, ETL readers, factor loader
├── api/             # FastAPI application
├── dashboard/       # Streamlit pages
└── etl/             # ETL pipeline orchestrator + stages
```

Import direction (enforced by import-linter at wave 2):
`api/dashboard/etl → application → domain ← infrastructure`
