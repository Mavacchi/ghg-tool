# Carbontrace — Production Deployment Runbook

**Product**: Carbontrace GHG Accounting Tool  
**Tenant**: Gruppo Ceramiche Gresmalt S.p.A.  
**Version**: 1.0.0  
**Date**: 2026-05-14  
**Standards**: CSRD Directive 2022/2464/EU, ESRS E1, ISAE 3000

> This runbook covers production deployment only. For local development or
> demo usage, follow `docker-compose.quickstart.yml`. That file contains the
> comment "DO NOT use this file in production" and ships a named test JWT
> secret (`quickstart-only-jwt-secret-min-32-chars-not-prod`) that must never
> appear in any production configuration.

---

## 1. Architecture

```mermaid
graph TD
    Browser["Browser / User Agent"]
    TLS["TLS Terminator\n(nginx / Caddy / ALB)\nport 443"]
    Streamlit["Streamlit UI container\nport 8501 — cluster-internal only"]
    API["FastAPI / uvicorn container\nport 8000 — cluster-internal only"]
    DB["Managed PostgreSQL 15+\nschemas: ref · raw · calc · ops\nPITR enabled"]
    Vault["Secrets Manager\n(Vault / AWS SM / Azure KV)"]
    Redis["Redis 7+ (optional)\nproduction rate-limiter\nslowapi upgrade path"]
    LogAgg["Log Aggregator\n(CloudWatch / Loki / Splunk)"]

    Browser -->|"HTTPS :443"| TLS
    TLS -->|"HTTP :8501 cluster-internal"| Streamlit
    TLS -->|"HTTP :8000 direct API calls"| API
    Streamlit -->|"HTTP :8000 cluster-internal"| API
    API -->|"asyncpg / psycopg"| DB
    API -.->|"optional"| Redis
    Vault -.->|"inject secrets at startup"| API
    API -->|"structured JSON logs"| LogAgg
    Streamlit -->|"structured JSON logs"| LogAgg
```

**Key architectural decisions:**

- The `app` container (uvicorn) listens on plain HTTP `0.0.0.0:8000` inside
  the cluster. TLS is terminated exclusively at the edge.
- The `streamlit` container listens on plain HTTP `0.0.0.0:8501` inside the
  cluster and must NOT be exposed directly to the internet; it is only
  reachable through the TLS terminator.
- The API injects `Strict-Transport-Security`, `X-Frame-Options`,
  `Content-Security-Policy`, and `Referrer-Policy` on every response via
  `SecurityHeadersMiddleware` (SEC-P1-002, `src/ghg_tool/api/middleware/security_headers.py`).
  The TLS terminator's HSTS preload directive takes precedence in the
  outermost response.

---

## 2. Required Infrastructure

| Component | Minimum spec | Notes |
|---|---|---|
| PostgreSQL | 15+ managed | Point-in-time recovery (PITR) enabled; WAL archiving to object storage. See `docs/disaster_recovery.md`. |
| Container runtime | Kubernetes 1.27+ or Docker 24+ on a VM | `docker-compose.yml` is the canonical reference. Compose v2 syntax. |
| TLS terminator | nginx 1.25+, Caddy 2.7+, or AWS ALB | App itself speaks plain HTTP inside the cluster. |
| Secrets manager | HashiCorp Vault, AWS Secrets Manager, or Azure Key Vault | All secrets injected as env vars at container startup — never baked into the image. |
| Redis | 7+ (optional) | Production upgrade path for multi-replica rate limiting via `slowapi`. The current in-process `RateLimitMiddleware` (`src/ghg_tool/api/middleware/rate_limit.py`) is not shared across replicas. |
| Log aggregator | CloudWatch, Loki, Splunk, or equivalent | Structured JSON. Container logs must be shipped off-host before local rotation. |
| Object storage | S3 / Azure Blob / GCS | WAL archive destination and logical backup storage. Retention per `docs/disaster_recovery.md`. |

---

## 3. Required Environment Variables

All secrets must be injected from the secrets manager at container startup.
No secret may be committed to version control or baked into the image.

| Variable | Example / Required value | Source | Notes |
|---|---|---|---|
| `GHG_JWT_SECRET` | 64 hex chars from CSPRNG | Secrets manager | Min 32 chars enforced at startup by `_load_jwt_secret()` in `src/ghg_tool/infrastructure/security/jwt.py` — app raises `RuntimeError` and refuses to start if absent or too short in production. |
| `GHG_JWT_ALGORITHM` | `HS256` (default) · `HS512` (recommended) · `RS256` (highest assurance) | Secrets manager or config | For RS256 also set `GHG_JWT_PUBLIC_KEY_PATH` and `GHG_JWT_PRIVATE_KEY_PATH` (PEM files mounted as secrets). `alg=none` is explicitly rejected at decode time (SG-01). |
| `GHG_JWT_PUBLIC_KEY_PATH` | `/run/secrets/jwt_public.pem` | Secret mount | Required only when `GHG_JWT_ALGORITHM=RS256`. |
| `GHG_JWT_PRIVATE_KEY_PATH` | `/run/secrets/jwt_private.pem` | Secret mount | Required only when `GHG_JWT_ALGORITHM=RS256`. |
| `GHG_JWT_ISSUER` | `https://carbontrace.gresmalt.it` | Config | Optional; enables `iss` claim validation on decode. |
| `GHG_JWT_AUDIENCE` | `carbontrace-api` | Config | Optional; enables `aud` claim validation on decode. |
| `GHG_ENVIRONMENT` | `production` | Config | Must be `production`: disables `/docs` and `/redoc` Swagger UI (`main.py` line 158–159); blocks demo-seed auto-seeding; enforces JWT secret presence at startup. |
| `GHG_CORS_ORIGINS` | `https://dashboard.gresmalt.it` | Config | Comma-separated HTTPS origins. Must NOT contain `*`. Wildcard CORS is explicitly forbidden (SEC-P1-001; see `main.py` comment on `_CORS_ORIGINS_RAW`). |
| `GHG_DEMO_MODE` | Must be unset or `false` | Config | When `GHG_ENVIRONMENT=production` the app skips demo-seeding regardless, but this variable must still be absent or `false` to prevent ambiguity. |
| `SQLALCHEMY_URL` | `postgresql+psycopg://ghg_app:***@db.internal:5432/ghg_tool` | Secrets manager | Sync DSN used by Alembic migrations and `scripts/create_user.py`. |
| `SQLALCHEMY_ASYNC_URL` | `postgresql+asyncpg://ghg_app:***@db.internal:5432/ghg_tool` | Secrets manager | Async DSN used by the FastAPI app at runtime. |
| `DATABASE_URL` | Same as `SQLALCHEMY_URL` | Secrets manager | Preferred env var consumed by `scripts/create_user.py` (`_dsn()` function). |
| `POSTGRES_PASSWORD` | Strong random password | Secrets manager | Used by the `db` service if running self-hosted Postgres via Compose. Not needed when connecting to a managed service via full DSN. |
| `GHG_COMPANY_NAME` | `Gresmalt` | Config | Tenant branding displayed in reports. |
| `GHG_TENANT_ID` | UUID of the `CERAMIC_TILE_CO` tenant row | Config | Populated by migrations; retrieve via `SELECT id FROM ref.tenants WHERE code='CERAMIC_TILE_CO'`. |
| `GHG_SITES` | `IANO,VIANO,VIANO_GARGOLA,CASALGRANDE,FIORANO,SASSUOLO,FRASSINORO` | Config | All 7 operational sites in scope (see `docs/methodology.md` Section 1). |
| `GHG_LOG_LEVEL` | `INFO` | Config | `DEBUG` must not be set in production; it may log sensitive request data. |
| `GHG_ACCESS_TOKEN_TTL` | `3600` (1 h default) | Config | Access token TTL in seconds (NFR-05). |
| `GHG_REFRESH_TOKEN_TTL` | `86400` (24 h default) | Config | Refresh token TTL in seconds (NFR-05). |

---

## 4. TLS Termination

The application does not terminate TLS. All HTTPS must be handled at the
edge. Below is a reference nginx configuration for a single-host VM
deployment. For AWS, use an ALB with an ACM certificate and a target group
pointing at port 8000.

```nginx
# /etc/nginx/sites-available/carbontrace

# Redirect all HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name dashboard.gresmalt.it;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name dashboard.gresmalt.it;

    # Certificate (use Certbot / ACME or your PKI)
    ssl_certificate     /etc/ssl/certs/gresmalt.crt;
    ssl_certificate_key /etc/ssl/private/gresmalt.key;

    # Modern cipher suite — TLS 1.2 minimum; TLS 1.3 preferred
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
                'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
                'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # OCSP stapling
    ssl_stapling on;
    ssl_stapling_verify on;

    # HSTS with preload (1 year — submit to https://hstspreload.org when ready)
    add_header Strict-Transport-Security
        "max-age=31536000; includeSubDomains; preload" always;

    # Direct API calls
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }

    # Streamlit dashboard (WebSocket upgrade required for Streamlit long-poll)
    location / {
        proxy_pass         http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 86400s;
    }

    # Healthcheck endpoint (accessible by load balancer, no auth required)
    location = /healthz {
        proxy_pass http://127.0.0.1:8000/healthz;
        access_log off;
    }
}
```

---

## 5. Pre-Deployment Checklist

Complete every item before routing production traffic. Leave no item
unchecked — partial completion is not acceptable for a CSRD-grade emissions
ledger.

- [ ] `GHG_JWT_SECRET` sourced from secrets manager. Not committed to any
  file in the repository. Not equal to `quickstart-only-jwt-secret-min-32-chars-not-prod`
  or `test-only-jwt-secret-min-32-chars-not-for-prod-xx`.
- [ ] `GHG_JWT_SECRET` is at least 32 characters (enforced at startup, but
  verify independently: `echo -n "$GHG_JWT_SECRET" | wc -c`).
- [ ] `GHG_ENVIRONMENT=production` set. Verify by confirming `/docs` returns
  HTTP 404 after starting the app.
- [ ] `GHG_DEMO_MODE` is unset or `false`.
- [ ] `GHG_CORS_ORIGINS` is set to one or more HTTPS origins and does NOT
  contain `*`.
- [ ] All 32 Alembic migrations applied (head `0032_M12`, internal nicknames
  M0 through M13 — see `alembic/versions/` for the chain). Run
  `alembic current` inside the container and confirm the output ends with
  `(head)`.
- [ ] At least one user with role `admin` seeded via
  `scripts/create_admin.py` (see Step 4 in Section 6). Note: roles were
  renamed from `esg_manager / data_steward / auditor` to
  `admin / editor / viewer` in wave 3.
- [ ] Backup schedule active and last backup verified (see
  `docs/disaster_recovery.md`).
- [ ] Log aggregation wired: container stdout/stderr reaching off-host store
  before local log rotation.
- [ ] `/healthz` endpoint wired to load balancer / container orchestrator
  healthcheck.
- [ ] TLS certificate valid. `curl -I https://dashboard.gresmalt.it/healthz`
  shows HTTP 200 and `Strict-Transport-Security` header.
- [ ] PostgreSQL PITR (WAL archiving) confirmed active on the managed DB.
- [ ] Encryption at rest enabled on the Postgres volume or managed DB instance.
- [ ] `POSTGRES_PASSWORD` (if self-hosted) is a strong random value, not
  `changeme`.

---

## 6. First-Time Deployment (Step-by-Step)

### Step 1 — Provision PostgreSQL 15+

Use a managed service (AWS RDS for PostgreSQL, Azure Database for PostgreSQL
Flexible Server, or GCP Cloud SQL for PostgreSQL) with the following settings:

- Engine version: PostgreSQL 15 or later.
- Point-in-time recovery: enabled (WAL archiving to object storage).
- Encryption at rest: enabled.
- Automated backups: nightly logical dump + continuous WAL (5-minute granularity
  or finer). See `docs/disaster_recovery.md` for retention settings.
- Database name: `ghg_tool`, application user: `ghg_app`.

### Step 2 — Pull or build the runtime image

```bash
# From a registry (preferred for production):
docker pull ghg-tool:1.0.0

# Or build from the repository root:
docker build --target runtime -t ghg-tool:1.0.0 .
```

The `Dockerfile` uses a two-stage build (`builder` → `runtime`). The runtime
image runs as non-root user `ghg` (created at build time, NFR-21) and exposes
port 8000. No build tools or dev dependencies are present in the runtime
image.

### Step 3 — Apply Alembic migrations

Run the migration one-shot against the production database before starting the
application. The `migrate` service in `docker-compose.yml` does this
automatically; for a bare container run:

```bash
docker run --rm \
  -e SQLALCHEMY_URL="postgresql+psycopg://ghg_app:<password>@<host>:5432/ghg_tool" \
  ghg-tool:1.0.0 \
  python -m alembic upgrade head
```

Verify with `alembic current` — output must end with `(head)`. All 10
migrations (M0–M9) seed reference data: tenants, roles, sites, emission factor
catalog, and GWP values. Do not skip any migration.

### Step 4 — Seed the initial admin user

```bash
docker run --rm -it \
  -e DATABASE_URL="postgresql+psycopg://ghg_app:<password>@<host>:5432/ghg_tool" \
  ghg-tool:1.0.0 \
  python -m scripts.create_user \
    --username admin@gresmalt.it \
    --email admin@gresmalt.it \
    --role esg_manager \
    --tenant-code CERAMIC_TILE_CO
```

The script reads the password from stdin (interactive double-prompt) or from
`GHG_NEW_USER_PASSWORD` env var; the password never appears in shell history
or process listings. Valid roles: `data_steward`, `esg_manager`, `auditor`.

Exit codes: 0 = created, 2 = already exists (safe to ignore on re-run), 3 =
tenant or role not found (means migrations were not applied).

### Step 5 — Start application containers

```bash
docker compose \
  --env-file /run/secrets/carbontrace.env \
  --profile app \
  up -d
```

The `--profile app` flag is required because the `app` service is
profile-gated in `docker-compose.yml` (the quickstart override removes this
gate for development). The `streamlit` service starts after `app` is healthy.

### Step 6 — Verify the healthcheck

```bash
curl -f https://dashboard.gresmalt.it/healthz
# Expected: HTTP 200
```

The `Dockerfile` HEALTHCHECK polls `http://localhost:8000/healthz` every 30 s
with a 5 s timeout, a 10 s start period, and 3 retries before marking the
container unhealthy.

### Step 7 — Run the smoke test

1. Open `https://dashboard.gresmalt.it` in a browser.
2. Log in with the `esg_manager` user created in Step 4.
3. Navigate to the KPI dashboard; confirm Scope 1 / Scope 2 totals render.
4. Call `GET /api/v1/emissions/scope1?year=2024` with a Bearer token; verify
   a JSON response with emission records for the 7 Gresmalt sites.
5. Confirm `GET /docs` returns HTTP 404 (Swagger UI disabled in production).
6. Confirm `curl -I https://dashboard.gresmalt.it` shows the
   `Strict-Transport-Security` header.

---

## 7. Rolling Update Procedure

1. Build and tag the new image: `ghg-tool:<new_version>`.
2. Push to the container registry.
3. Apply database migrations for the new version **before** updating running
   containers. Migrations that add columns are backward-compatible — the old
   code ignores unknown columns:
   ```bash
   docker run --rm \
     -e SQLALCHEMY_URL="postgresql+psycopg://ghg_app:***@<host>:5432/ghg_tool" \
     ghg-tool:<new_version> \
     python -m alembic upgrade head
   ```
4. Update the `app` service:
   - **Kubernetes**: `kubectl set image deployment/carbontrace-app app=ghg-tool:<new_version>`
   - **Docker Compose on VM**: `docker compose --profile app up -d --no-deps app`
5. Wait for the new `app` container's healthcheck to pass (poll `/healthz`).
6. Update the `streamlit` service the same way.
7. Run the smoke test (Section 6, Step 7).
8. Monitor logs for 10 minutes post-deploy for unexpected 5xx responses.

---

## 8. Rollback Procedure

> Rollback reverts the application image only. It does NOT revert database
> migrations. If a migration rollback is needed, treat it as a DR event and
> follow `docs/disaster_recovery.md`.

1. Identify the last known-good image tag from the container registry.
2. Re-deploy the previous image using the same rolling update steps as
   Section 7, substituting the previous tag.
3. If the current schema is incompatible with the previous image:
   - **Option A (preferred)**: Deploy a hotfix image that tolerates the
     current schema.
   - **Option B**: Restore from the most recent pre-migration backup. This
     is a DR event; follow `docs/disaster_recovery.md` Section 5 and execute
     the communication plan in Section 7 of that document.
4. Verify `/healthz` returns 200 and re-run the smoke test.
5. Record the rollback in the incident log: timestamp, version rolled back
   from, version rolled back to, root cause, and approver.

---

## References

- `docs/disaster_recovery.md` — backup, PITR, and DR procedure
- `docs/methodology.md` — ESG calculation methodology (v1.0.0)
- `docker-compose.yml` — service definitions (development / integration)
- `docker-compose.quickstart.yml` — quickstart override (development only, contains explicit "DO NOT use in production" comment)
- `Dockerfile` — two-stage build; non-root user `ghg`; exposes port 8000
- `src/ghg_tool/api/main.py` — middleware stack; env var consumption
- `src/ghg_tool/infrastructure/security/jwt.py` — JWT secret loading and algorithm validation
- `src/ghg_tool/api/middleware/security_headers.py` — HSTS, CSP, X-Frame-Options (SEC-P1-002)
- `src/ghg_tool/api/middleware/rate_limit.py` — in-process rate limiter; Redis upgrade path
- `scripts/create_user.py` — admin user seeding CLI
- `alembic/versions/` — 10 migrations M0–M9
