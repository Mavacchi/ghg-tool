# Deployment Runbook — GHG Accounting Tool v1

**Version**: 1.0.0
**Date**: 2026-05-14
**Status**: APPROVED for production use — Security APPROVED (Phase 8), Compliance APPROVED (Phase 8)
**Closes**: SEC-ADV-008, SEC-ADV-009, SEC-ADV-010

This document is the authoritative production deployment runbook. It must be read in full
by the operator before any production deployment. Sections marked **RISK** describe
acknowledged security trade-offs that have been reviewed and accepted for v1 with explicit
v2 remediation roadmap items.

---

## Prerequisites

| Component | Minimum version | Notes |
|---|---|---|
| PostgreSQL | 15+ | 15 is required for `current_setting(..., true)` (missing_ok) in RLS and security-barrier view syntax used in M4/M7 migrations |
| Python | 3.11+ | Pinned in `pyproject.toml`; do not deploy with 3.10 or earlier |
| Docker | 24+ | Docker Compose v2 syntax used in `docker-compose.yml` |
| Reverse proxy | nginx 1.24+ or Caddy 2.7+ | TLS termination MUST occur at the proxy; do NOT terminate TLS in the FastAPI application |
| RAM | >= 2 GB available to the application container | ETL batch processing peak; PDF rendering via WeasyPrint |
| Persistent volume | >= 20 GB for PostgreSQL data directory | Emission records + factor catalog + audit log for 10-year retention |

---

## Environment Variables

All variables must be set in the deployment environment (Docker secrets, `.env` file,
or cloud secret manager). Variables marked **REQUIRED** will cause a startup error or
insecure behaviour if absent.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GHG_JWT_SECRET` | **REQUIRED** | none | JWT signing secret for HS256. Must be >= 32 characters. The application raises `RuntimeError` at startup if the secret is shorter (SEC-P0-001 enforcement). Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GHG_ENVIRONMENT` | **REQUIRED** | none | Runtime environment: `production`, `staging`, `development`, or `test`. Controls demo-mode defaults, error verbosity, and CORS policy. Must be `production` in production deployments. |
| `DATABASE_URL` | **REQUIRED** | none | Synchronous SQLAlchemy URL for Alembic migrations: `postgresql+psycopg2://ghg_app:<password>@<host>:5432/ghg` |
| `SQLALCHEMY_URL` | **REQUIRED** | none | Synchronous SQLAlchemy URL for the application: `postgresql+psycopg2://ghg_app:<password>@<host>:5432/ghg` |
| `SQLALCHEMY_ASYNC_URL` | **REQUIRED** | none | Async SQLAlchemy URL for FastAPI async endpoints: `postgresql+asyncpg://ghg_app:<password>@<host>:5432/ghg` |
| `GHG_CORS_ORIGINS` | Recommended | `""` (empty — no CORS) | Comma-separated list of allowed origins for CORS, e.g. `https://dashboard.example.com`. Empty string disables CORS. See SEC-ADV-009 note below. |
| `GHG_DEMO_MODE` | Optional | `false` | When `true`, enables demo fixtures and relaxed seed data. Must be `false` in production. |
| `GHG_API_BASE_URL` | Required for Streamlit | `http://localhost:8000` | Base URL of the FastAPI service, as seen by the Streamlit container. In production: `https://api.example.com` |
| `GHG_TENANT_ID` | Required for Streamlit | none | UUID of the default tenant used by the Streamlit session GUC middleware. Must match the `ref.tenants.id` seeded during database setup. |

---

## Database Setup

### 1. Create the application role and database

Connect as a PostgreSQL superuser and run:

```sql
CREATE ROLE ghg_app LOGIN PASSWORD '<strong-password>';
CREATE DATABASE ghg OWNER ghg_app;
```

### 2. Run Alembic migrations

```bash
# From the repository root, with DATABASE_URL set:
alembic upgrade head
```

Migrations apply in sequence: M0 (base schema + schemas + shared mutation guard) through
M7 (security-barrier views). Each migration is idempotent. Running `alembic upgrade head`
twice is safe.

Expected final state after `alembic upgrade head`:

| Migration | Description |
|---|---|
| 0001_M0 | Schemas (raw, ref, calc, mv, ops), extensions, shared mutation guard function, ref.tenants, ref.roles, ref.users, gwp_sets (AR6+AR5 seeded) |
| 0002_M1 | calc.emissions_consolidated with bitemporal columns, `trg_emissions_deny_mutation` trigger, `calc.fn_emit_correction()` stored procedure |
| 0003_M2 | Raw staging tables (raw.scope1_ingestions, raw.scope2_ingestions, raw.scope3_ingestions) |
| 0004_M3 | calc.dq_findings, calc.dlq, calc.audit_log — all append-only |
| 0005_M4 | PostgreSQL Row-Level Security policies on raw.* and calc.* tables; GUC `app.tenant_id` pattern |
| 0006_M5 | ref.factor_catalog schema; go_certificate_evidence table |
| 0007_M6 | Materialised views calc.mv_kpi_summary and calc.mv_intensity_metrics |
| 0008_M7 | Security-barrier views calc.v_kpi_summary and calc.v_intensity_metrics; REVOKE direct MV access from ghg_app |

### 3. Grant setup verification

After migrations, verify:

```sql
-- Application role must have SELECT on views but NOT on underlying MVs
SELECT has_table_privilege('ghg_app', 'calc.v_kpi_summary', 'SELECT');       -- must be true
SELECT has_table_privilege('ghg_app', 'calc.mv_kpi_summary', 'SELECT');      -- must be false
SELECT has_table_privilege('ghg_app', 'calc.v_intensity_metrics', 'SELECT'); -- must be true
SELECT has_table_privilege('ghg_app', 'calc.mv_intensity_metrics', 'SELECT'); -- must be false
```

### 4. Materialised view refresh schedule

The KPI and intensity materialised views must be refreshed periodically so that the
security-barrier views surface current data. Schedule a concurrent refresh:

```sql
-- Run as the superuser or migration role (NOT as ghg_app, which lacks MV access)
REFRESH MATERIALIZED VIEW CONCURRENTLY calc.mv_kpi_summary;
REFRESH MATERIALIZED VIEW CONCURRENTLY calc.mv_intensity_metrics;
```

Recommended schedule: **hourly** via `cron` or `pg_cron`. Example crontab entry:

```
0 * * * * psql -U postgres -d ghg -c "REFRESH MATERIALIZED VIEW CONCURRENTLY calc.mv_kpi_summary; REFRESH MATERIALIZED VIEW CONCURRENTLY calc.mv_intensity_metrics;"
```

Alert if refresh latency exceeds 5 minutes (see Monitoring section).

---

## TLS Termination

TLS must be terminated at the reverse proxy. The FastAPI application (`uvicorn`) listens
on HTTP internally and must never be exposed directly on port 443.

**Recommended nginx configuration excerpt**:

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/ssl/certs/api.example.com.crt;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass         http://ghg_api:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name api.example.com;
    return 301 https://$host$request_uri;
}
```

---

## Acknowledged Risks for Production

The following risks are acknowledged, documented, and accepted for v1 deployment.
Each has an explicit v2 remediation item in `docs/roadmap.md`.

### SEC-ADV-008 — Rate limiter is in-process (per pod)

**Risk description**: The 5-per-minute login rate limit (SEC-P1-003) is implemented using
slowapi with an in-memory store. In a single-worker, single-replica deployment this
functions correctly. In a multi-replica (horizontal scale) deployment, each pod maintains
an independent counter: a credential-stuffer can reach 5 x N login attempts per minute
where N is the replica count, without triggering any single pod's limit.

**Affected component**: `src/ghg_tool/api/middleware/rate_limit.py`

**Severity for v1 single-worker deployment**: Low. The v1 deployment profile is a
single-worker Docker container behind a reverse proxy. The risk is not realised in this
topology.

**Mitigation for multi-replica deployment**: Either (a) configure sticky sessions at the
load balancer so that all requests from a given source IP route to the same pod, or
(b) migrate the slowapi storage backend to Redis. Option (b) is the correct long-term fix.

**v2 roadmap**: SEC-ADV-008 is tracked as a v2 item in `docs/roadmap.md`. Before horizontal
scaling is enabled, Redis-backed rate limiting must be deployed.

**Operator action required**: If the deployment topology includes more than one API replica,
implement sticky sessions at the load balancer **before** enabling multi-replica mode.
Document the decision in the operations runbook.

### SEC-ADV-009 — CORS allow_credentials=False default

**Risk description**: The application's CORS configuration defaults to
`allow_credentials=False`. All current authorisation flows use the `Authorization: Bearer
<token>` header, which does not require `allow_credentials=True`. This is correct for the
current design.

**If cookie-based authentication is ever enabled**: Setting `allow_credentials=True` in
the CORS middleware is required for cookies to be sent cross-origin. However, the
application has **no CSRF middleware** in v1. Enabling `allow_credentials=True` without
adding CSRF protection creates a Cross-Site Request Forgery vulnerability.

**Operator action required**: Do not enable cookie-based authentication without
simultaneously adding CSRF middleware (e.g. `starlette-csrf`) and explicitly documenting
the decision. The `GHG_CORS_ORIGINS` variable controls the origins whitelist. An empty
value disables all CORS.

**v2 roadmap**: If cookie-based auth is adopted (e.g. for same-site SSO integration),
CSRF protection must be added as a simultaneous change.

### SEC-ADV-010 — Content Security Policy and Streamlit dashboard

**Risk description**: The API applies a strict `Content-Security-Policy: default-src
'self'` header. The Streamlit dashboard uses Plotly for interactive charts, which requires
`script-src 'unsafe-inline'` and `style-src 'unsafe-inline'` to function correctly. These
directives are incompatible with a strict CSP.

**Affected scope**: In v1 the FastAPI API and the Streamlit dashboard are served on
**different origins** (different ports or different hostnames). The CSP header on the API
does not govern the Streamlit origin. However, if the two components are ever served under
the same origin or the dashboard is embedded via an iframe on a controlled page, this
creates a conflict.

**Operator action required before rolling out the dashboard**:

1. Verify end-to-end with browser developer tools that Plotly charts render correctly under
   the deployment CSP.
2. If the dashboard is served under the same origin as the API, add a path-specific CSP
   relaxation for `/dashboard/*`:
   ```
   Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'
   ```
3. Document the relaxation decision in this runbook before enabling it.

**v2 roadmap**: Evaluate migrating interactive charts to a CSP-compatible rendering path
(e.g. server-side SVG rendering) to eliminate `unsafe-inline` requirements.

---

## Backup and Restore

### Backup policy

```bash
# Nightly full logical backup — run as superuser or backup role
pg_dump -U postgres -Fc -f /backups/ghg_$(date +%Y%m%d).dump ghg

# Retain 30 days of daily backups; purge older files
find /backups/ -name "ghg_*.dump" -mtime +30 -delete
```

Backup files must be encrypted at rest (AES-256) using the cloud provider's storage
encryption or `gpg --symmetric` before transfer off-site. The encryption key must be
stored separately from the backup files (key management system or offline vault).

### Restore procedure

**Standard restore** (to a clean PostgreSQL 15 instance):

```bash
# 1. Create the ghg_app role and ghg database (see Database Setup above)
# 2. Restore
pg_restore -U postgres -d ghg --no-owner --role=ghg_app /backups/ghg_YYYYMMDD.dump
# 3. Re-run migrations to ensure trigger and view state is current
alembic upgrade head
```

### Immutable audit log restoration

The append-only audit trail (`calc.audit_log`, `calc.emissions_consolidated`,
`calc.dq_findings`, `calc.dlq`) cannot be restored by UPDATE. If a partial restore is
required after data corruption:

1. Restore the backup to a **new tenant_id** space (insert a new row in `ref.tenants`
   with a different `code` value).
2. Import the affected rows with the new `tenant_id` as INSERT statements.
3. Do not re-link the restored rows to the original `tenant_id` — this would create
   duplicate natural-key conflicts in the active partition.
4. Retain both the original (potentially corrupted) and restored rows; the ISAE 3000
   assurance provider must be notified of any restoration event for chain-of-custody
   continuity.

---

## Monitoring and Alerts

### Log pipeline

The application emits structured JSON logs via `structlog`. Route to ELK (Elasticsearch
+ Logstash + Kibana) or Grafana Loki + Promtail. All log lines are PII-free: usernames
are SHA-256 hashed to a 16-char prefix (SEC-P0-005).

### Key alert rules

| Alert | Log field / query | Threshold | Action |
|---|---|---|---|
| Credential-stuffing probe | `probe_attempt=True` in `/api/v1/auth/login` or `/api/v1/auth/refresh` log lines | > 10 events in 5 minutes from any single source | Notify security on-call; consider IP block at reverse proxy |
| DLQ backlog | `SELECT COUNT(*) FROM calc.dlq WHERE replay_status='PENDING'` | > 0 rows | Notify data_steward; investigate DQ gate failure |
| MV refresh latency | Wall-clock time between consecutive refresh completions | > 5 minutes | Notify IT Operations; dashboard data may be stale |
| Login rate limit exceeded | HTTP 429 responses on `/api/v1/auth/login` | > 5 in 1 minute from a single IP | Notify security on-call |
| JWT startup assertion | `RuntimeError: GHG_JWT_SECRET must be at least 32 characters` | Any occurrence | Application will not start; rotate secret and redeploy |

---

## Smoke Test Checklist

Run after every production deployment to verify end-to-end functionality:

```bash
BASE=https://api.example.com

# 1. Login — obtain tokens
RESPONSE=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"esg_manager","password":"<password>"}')
ACCESS=$(echo $RESPONSE | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. GET /kpis — verify emissions data accessible
curl -s -H "Authorization: Bearer $ACCESS" "$BASE/api/v1/kpis" | python3 -m json.tool

# 3. GET /intensity — verify intensity ratios accessible
curl -s -H "Authorization: Bearer $ACCESS" "$BASE/api/v1/intensity" | python3 -m json.tool

# 4. POST /exports/pdf — request PDF generation
PDF_RESPONSE=$(curl -s -X POST "$BASE/api/v1/exports/pdf" \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d '{"anno":2024,"gwp_set":"AR6","lang":"it"}')
PDF_JOB_ID=$(echo $PDF_RESPONSE | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 5. Retrieve PDF and validate magic bytes (PDF starts with %PDF-)
curl -s -H "Authorization: Bearer $ACCESS" \
  "$BASE/api/v1/exports/pdf/$PDF_JOB_ID" -o /tmp/test_report.pdf
head -c 5 /tmp/test_report.pdf | od -c | grep '%   P   D   F   -'
# Must output a matching line; if empty the PDF export is broken

# 6. Verify audit trail has entries (non-empty means writes are being logged)
curl -s -H "Authorization: Bearer $ACCESS" "$BASE/api/v1/audit-trail?limit=1" | python3 -m json.tool
```

All six steps must succeed before declaring the deployment healthy.
