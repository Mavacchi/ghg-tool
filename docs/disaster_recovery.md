# Carbontrace — Disaster Recovery and Backup Procedure

**Product**: Carbontrace GHG Accounting Tool  
**Tenant**: Gruppo Ceramiche Gresmalt S.p.A.  
**Version**: 1.0.0  
**Date**: 2026-05-14  
**Standards**: CSRD Directive 2022/2464/EU Article 33 (record retention), ISO 22301:2019 (Business Continuity Management)

> Prerequisites: a running production deployment per `docs/deployment.md`.
> This document is written for operations staff who may not be application
> developers. Every step that requires application code is called out
> explicitly.

---

## 1. RTO and RPO Targets

| Target | Value | Justification |
|---|---|---|
| **RTO** (Recovery Time Objective) | 4 hours | Carbontrace is not a real-time transaction system. A 4-hour window allows a single on-call operator to restore from a verified WAL backup, run Alembic validation, and hand off to the ESG manager for data integrity confirmation — all within a business day. |
| **RPO** (Recovery Point Objective) | 1 hour | WAL segments are archived to object storage every 5 minutes. In the worst case (failure immediately before a WAL flush) the maximum data loss is bounded by the WAL archive interval. A 1-hour RPO comfortably encompasses that interval and the time for ops to detect the failure. |

These targets apply to the full stack (PostgreSQL + API + Streamlit). For
CSRD reporting purposes, the `calc.*` schema (consolidated emissions and audit
log) is the business-critical dataset; `raw.*` staging data has relaxed RPO
because it can be re-ingested from source files.

---

## 2. Backup Strategy

### 2.1 Backup types

| Type | Tool | Frequency | Destination | Encryption |
|---|---|---|---|---|
| Logical backup | `pg_dump` (custom format) | Nightly, 02:00 UTC | Object storage (S3 / Azure Blob / GCS) | SSE-KMS (AWS) or CMK (Azure) or CSEK (GCP) |
| WAL archive (PITR) | `archive_command` / managed DB continuous backup | Continuous; flush every 5 minutes | Same object storage bucket, separate prefix | Same encryption at rest |
| Pre-migration snapshot | `pg_dump` | Before every `alembic upgrade head` in production | Same bucket, `pre-migration/` prefix | Same |

### 2.2 Retention schedule

| Data | Retention | Basis |
|---|---|---|
| `calc.*` schemas (consolidated emissions, KPI results) | 10 years | CSRD Directive 2022/2464/EU Article 33 |
| `calc.audit_log` and `ref.audit_log` | 10 years | Same; also ISAE 3000 assurance requirements |
| `raw.*` schemas (staging ingestions) | 90 days | Staging data is consumed into `calc.*`; original source files held by Gresmalt's ERP systems |
| `ref.*` schemas (reference data, factor catalog) | 7 years | Italian Codice Civile art. 2220; also needed for recalculation audit |
| `ops.*` schemas (operational metadata) | 7 years | Consistent with `ref.*` |
| Full logical backups | 10 years (aligned with `calc.*` retention) | Simplest policy; overly cautious for `raw.*` but avoids split-tape complexity |
| WAL segments | 30 days rolling | Provides 30-day PITR window at reasonable storage cost |

### 2.3 Backup storage configuration

Object storage bucket requirements:

- Versioning enabled (prevents accidental deletion of backup files).
- Object Lock / immutable storage enabled (prevents ransomware deletion).
- Replication to a second region (required for PITR files; recommended for
  logical dumps).
- Access restricted to: the backup service account, the on-call DBA role, and
  the DR automation principal. No public access.
- Lifecycle rule: transition WAL segments older than 30 days to Glacier /
  Archive tier; retain logical dumps per retention schedule above.

### 2.4 Sample backup command (manual reference)

```bash
# Logical backup — run from a host with network access to the DB
pg_dump \
  --format=custom \
  --compress=9 \
  --file="/backup/ghg_tool_$(date -u +%Y%m%dT%H%M%SZ).pgdump" \
  "postgresql://ghg_app:<password>@<host>:5432/ghg_tool"

# Upload to S3
aws s3 cp \
  "/backup/ghg_tool_$(date -u +%Y%m%dT%H%M%SZ).pgdump" \
  "s3://gresmalt-carbontrace-backup/logical/ghg_tool_$(date -u +%Y%m%dT%H%M%SZ).pgdump" \
  --sse aws:kms \
  --sse-kms-key-id "<kms-key-arn>"
```

For managed services (RDS, Azure, Cloud SQL), use the native snapshot / PITR
capability in preference to manual `pg_dump`. The native capability is
integrated with the WAL archiving pipeline.

---

## 3. Restore Procedure

This procedure can be executed by operations staff without application
developer involvement. Steps are ordered; do not skip steps.

### Step 1 — Declare a DR event and notify stakeholders

Follow the communication plan in Section 7 before making any changes. Log the
event start time, the nature of the failure, and the operator performing the
restore.

### Step 2 — Stop the application containers

```bash
docker compose --profile app down
# Or for Kubernetes:
kubectl scale deployment carbontrace-app --replicas=0
kubectl scale deployment carbontrace-streamlit --replicas=0
```

Stopping the app before restoring prevents split-brain: new writes arriving
during a restore would be lost, corrupting the audit trail.

### Step 3 — Determine the restore target

Choose one of:

**Option A — Latest WAL position (most common)**: restore to the most recent
consistent state. Use the managed DB's "restore to latest" capability or
`pg_restore` from the most recent WAL-consistent snapshot.

**Option B — Point-in-time (PITR)**: restore to a specific timestamp. Use
this when the failure is data corruption introduced at a known time (e.g. a
bad migration ran at 14:32 UTC — restore to 14:30 UTC).

```
# Example PITR target for managed Postgres (adjust syntax per provider):
# AWS RDS: restore-db-instance-to-point-in-time --restore-time 2026-05-14T14:30:00Z
# Azure: az postgres flexible-server restore --restore-time "2026-05-14T14:30:00Z"
```

For PITR, record the target timestamp in the incident log. The timestamp
determines which WAL segments are replayed; segments after the target are
discarded.

### Step 4 — Execute the restore

For managed services, use the provider's native restore UI or CLI. The
restored instance will be created as a new DB instance (most providers do not
restore in-place).

For self-hosted or `pg_dump`-based restore:

```bash
# Drop and recreate the target database (destructive — confirm before running)
psql -U postgres -c "DROP DATABASE IF EXISTS ghg_tool;"
psql -U postgres -c "CREATE DATABASE ghg_tool OWNER ghg_app;"

# Restore from the chosen .pgdump file
pg_restore \
  --dbname="postgresql://postgres:<password>@<host>:5432/ghg_tool" \
  --no-owner \
  --no-privileges \
  --verbose \
  "/restore/ghg_tool_<timestamp>.pgdump"
```

### Step 5 — Verify schema version with Alembic

```bash
docker run --rm \
  -e SQLALCHEMY_URL="postgresql+psycopg://ghg_app:<password>@<restored-host>:5432/ghg_tool" \
  ghg-tool:1.0.0 \
  python -m alembic current
```

Expected output: the head revision hash followed by `(head)`.

**If the output does NOT end with `(head)`:**

The restored database schema is behind the current application code. Two
options:

- **Roll forward** (apply the missing migrations to the restored DB):
  ```bash
  python -m alembic upgrade head
  ```
  Safe only if the missing migrations are additive (new columns, new tables).
  Do not roll forward if the missing migrations drop or alter existing columns.

- **Restore an older backup** (from before the first migration that caused
  the schema drift) and re-apply all migrations from that point. Prefer this
  option if there is any doubt.

### Step 6 — Verify append-only trigger integrity

The immutability triggers on `calc.emissions_scope1`, `calc.emissions_scope2`,
and `calc.emissions_scope3` (installed by migration MG-02) must survive the
restore because they are part of the schema DDL. Verify:

```sql
-- Run against the restored database
SELECT trigger_name, event_manipulation, event_object_table
FROM information_schema.triggers
WHERE trigger_schema = 'calc'
  AND trigger_name LIKE '%immutable%'
ORDER BY event_object_table, trigger_name;
```

Expected: at least one trigger per emission table for `UPDATE` and `DELETE`
events. If triggers are missing, do NOT start the application — the
append-only ledger guarantee has been lost. Re-apply the MG-02 migration DDL
manually and re-verify.

### Step 7 — Verify audit log integrity

```sql
-- Confirm audit_log is intact and ordered correctly
SELECT
    id,
    occurred_at,
    actor_sub,
    action,
    table_name
FROM calc.audit_log
ORDER BY occurred_at DESC
LIMIT 50;
```

Look for: no gaps in `occurred_at` sequence, no unexpected `DELETE` or
`UPDATE` action codes (the triggers block these at DB level, so their presence
would indicate tampering or a restore from a corrupted backup). If anomalies
are found, escalate to the ESG manager and external auditor before proceeding.

### Step 8 — Update the application DSN and restart

Update `SQLALCHEMY_URL`, `SQLALCHEMY_ASYNC_URL`, and `DATABASE_URL` to point
to the restored DB instance (the host name may have changed if using a managed
service restore-to-new-instance flow).

```bash
docker compose \
  --env-file /run/secrets/carbontrace-restored.env \
  --profile app \
  up -d
```

### Step 9 — Verify healthcheck and run smoke test

```bash
curl -f https://dashboard.gresmalt.it/healthz
# Expected: HTTP 200
```

Then perform the full smoke test from `docs/deployment.md` Section 6, Step 7.

### Step 10 — Log the completed restore and notify stakeholders

Record in the incident log:
- Event start time and end time.
- Operator(s) involved.
- Restore type (latest WAL / PITR target timestamp).
- Backup file or snapshot used.
- Alembic revision confirmed.
- Trigger integrity verified: yes/no.
- Audit log anomalies found: yes/no (details if yes).
- Stakeholders notified (see Section 7).

---

## 4. Restore Test Schedule

Backup files that have never been tested are not backups — they are hopes.

| Activity | Frequency | Owner | Standard |
|---|---|---|---|
| Automated backup integrity check (verify checksum of latest `pg_dump` file) | Daily (automated) | Ops | — |
| Full restore drill to isolated environment | Quarterly | DBA + ESG manager | ISO 22301:2019 §8.5 |
| PITR drill to specific timestamp | Annually | DBA | ISO 22301:2019 §8.5 |
| Trigger + audit log integrity verification post-restore | Every restore drill | DBA | CSRD Article 33 |

**Quarterly restore drill procedure:**

1. Provision an isolated PostgreSQL 15 instance (no network access to
   production).
2. Restore the most recent nightly `pg_dump` from the backup bucket.
3. Execute Steps 5 through 7 of the restore procedure above.
4. Start the application containers pointed at the isolated instance and run
   the smoke test from `docs/deployment.md` Section 6, Step 7.
5. Destroy the isolated instance.
6. Record results in the DR log with: date, backup age, restore duration,
   issues found, sign-off by ESG manager.

The ISO 22301:2019 standard (Section 8.5, Exercise and testing) requires that
BC plans are tested at planned intervals and that the results are documented,
reviewed by management, and used to improve the plans.

---

## 5. Append-Only Ledger Considerations

### Trigger survival across restores

The database-level immutability triggers (migration MG-02) that block `UPDATE`
and `DELETE` on the `calc.emissions_*` tables are part of the PostgreSQL
schema DDL. A `pg_dump --format=custom` backup includes all DDL, so the
triggers are restored along with the data. This must be verified at each
restore (Step 6 above).

A `pg_dump --data-only` restore would NOT include triggers. Never use
`--data-only` for a production restore unless you explicitly re-apply the full
schema DDL separately.

### Detecting tampering at restore time

A restore from a tampered or manipulated backup file cannot be detected purely
by schema inspection. The `calc.audit_log` integrity query in Step 7 provides
a first-order check, but a sophisticated attacker who also modified the audit
log would evade it.

**Recommended future hardening — `ops.audit_log_hash_chain`:**

Implement a hash chain over `calc.audit_log` rows: each row stores
`sha256(previous_hash || row_content)`. On restore, the chain can be replayed
from genesis and compared against the expected tip hash stored off-database
(e.g. in the secrets manager). Any tampering breaks the chain at the tampered
row.

This is a future hardening item. Until it is implemented, the primary tamper
detection relies on the PostgreSQL trigger mechanism and the immutability of
the object-storage backup files (Object Lock / Immutable Blob).

### Recalculation records

Per `docs/methodology.md` (Section on Recalculation Policy), GHG Protocol
baseline recalculations produce new records with a `recalculation_id` — they
do not modify existing records. A restore therefore always preserves the full
history including both original and recalculated rows. Do not manually delete
recalculation records after a restore even if they appear redundant.

---

## 6. Key Rotation After a DR Event

If a DR event was caused by or involved a suspected credential exposure:

1. Rotate `GHG_JWT_SECRET` via the secrets manager immediately. All existing
   sessions are invalidated because JWT validation fails without the old
   secret. Users must re-login.
2. Rotate `POSTGRES_PASSWORD` / DB credentials and update all DSN env vars.
3. Rotate the object storage access keys used for backup.
4. Review `calc.audit_log` for any unexpected `auth.login` events from
   unknown `actor_sub` values during the exposure window.
5. Notify the DPO (see `docs/gdpr/dpia.md`) if a data breach is suspected.
   GDPR Article 33 requires notification to the supervisory authority within
   72 hours of becoming aware of a personal data breach.

---

## 7. Communication Plan

| Milestone | Who to notify | Channel | SLA |
|---|---|---|---|
| DR event declared | ESG manager, IT manager, on-call DBA | Phone + email | Immediately (< 15 min of declaration) |
| Restore started | ESG manager | Email | Within 30 min of restore start |
| Restore completed, integrity verified | ESG manager, CFO | Email | Within 1 h of completion |
| Any audit-log anomaly detected | ESG manager, CFO, external auditor (under NDA) | Email + phone | Immediately |
| Suspected personal data breach | DPO | Phone + email | Immediately; DPO to assess GDPR Art. 33 notification requirement (72 h window to supervisory authority) |
| DR event closed | ESG manager, CFO, IT manager | Email | Within 24 h of restoration |

**On-call rotation**: the IT manager must maintain a 24/7 on-call rotation
covering the DBA and ops roles. Contact details must be stored outside the
Carbontrace system (e.g. in a physical runbook or separate communication
platform) so they are accessible during a total system outage.

---

## References

- `docs/deployment.md` — production deployment prerequisites and smoke test
- `docs/methodology.md` — recalculation policy (GHG Protocol Corporate Standard cap. 5)
- `docs/gdpr/dpia.md` — GDPR obligations in a DR / data breach scenario
- `alembic/versions/` — migration history including MG-02 (immutability triggers)
- CSRD Directive 2022/2464/EU, Article 33 — sustainability information retention
- ISO 22301:2019 — Business Continuity Management Systems
- GHG Protocol Corporate Standard (2004), Chapter 5 — Recalculation policy
