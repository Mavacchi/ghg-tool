"""M9 — 10-year audit log retention via pg_cron monthly archive job.

10-year retention enforced via pg_cron monthly archive job. Retention
rationale: CSRD Art. 23(2) audit trail + GDPR Art. 5(1)(e) data
minimization.

Strategy (non-disruptive, no partition migration required)
==========================================================
Given that ``calc.audit_log`` is already populated in production, a full
partition-based migration would require a dump+restore cycle (deferred to
a future migration).  Instead this migration implements a lighter-weight
archive pattern:

1. Create schema ``calc_archive`` (if not exists).
2. Create table ``calc_archive.audit_log_archive`` with the same column
   structure as ``calc.audit_log``.  The archive table deliberately has
   NO append-only trigger — archived rows are legal to update/delete
   (e.g., for GDPR erasure requests handled by DBAs).
3. Add a sanity CHECK on ``occurred_at >= '2020-01-01'`` to the archive
   table to catch obviously wrong inserts.
4. Register a monthly pg_cron job (``0 3 1 * *``, i.e. 1st of each month
   at 03:00 UTC) named ``audit_log_archive`` that:
     a. Copies rows older than 10 years from ``calc.audit_log`` into
        ``calc_archive.audit_log_archive``.
     b. Deletes those same rows from ``calc.audit_log``, temporarily
        disabling the ``trg_audit_log_deny_mutation`` trigger so the
        DELETE is permitted (same pattern used in 0028_M8 downgrade).
5. Graceful degrade: if pg_cron is not available the migration succeeds
   with a NOTICE (same EXCEPTION pattern as 0027_M7).

Downgrade
=========
- Unschedule ``audit_log_archive`` pg_cron job (if pg_cron present).
- DROP SCHEMA calc_archive CASCADE.

Revision: 0029_M9
Revises:  0028_M8
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0029_M9"
down_revision: str = "0028_M8"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PL/pgSQL block: create archive schema + table, then register pg_cron job.
# Graceful degrade if pg_cron is unavailable (same pattern as 0027_M7).
# ---------------------------------------------------------------------------
_UPGRADE_BLOCK = """\
DO $$
DECLARE
    _cron_available BOOLEAN := FALSE;
BEGIN
    -- -----------------------------------------------------------------------
    -- Step 1: create calc_archive schema
    -- -----------------------------------------------------------------------
    CREATE SCHEMA IF NOT EXISTS calc_archive;

    -- -----------------------------------------------------------------------
    -- Step 2: create archive table (mirrors calc.audit_log; no immutability
    -- trigger so that GDPR erasure DELETEs can be applied by DBAs).
    -- CHECK (occurred_at >= '2020-01-01') is a sanity guard only.
    -- -----------------------------------------------------------------------
    CREATE TABLE IF NOT EXISTS calc_archive.audit_log_archive (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id       UUID         NOT NULL,
        correlation_id  UUID         NOT NULL,
        occurred_at     TIMESTAMPTZ  NOT NULL CHECK (occurred_at >= '2020-01-01'),
        user_id         UUID,
        user_role       VARCHAR(40)  NOT NULL,
        action          VARCHAR(60)  NOT NULL,
        resource        VARCHAR(60),
        resource_id     UUID,
        request_method  VARCHAR(10),
        request_path    TEXT,
        status_code     SMALLINT,
        ip_address      INET,
        user_agent      TEXT,
        before_state    JSONB,
        after_state     JSONB,
        extra           JSONB,
        archived_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
    );

    CREATE INDEX IF NOT EXISTS ix_al_archive_tenant_time
        ON calc_archive.audit_log_archive (tenant_id, occurred_at DESC);

    -- -----------------------------------------------------------------------
    -- Step 3: attempt to enable pg_cron (graceful degrade on failure)
    -- -----------------------------------------------------------------------
    BEGIN
        CREATE EXTENSION IF NOT EXISTS pg_cron;
        _cron_available := TRUE;
    EXCEPTION
        WHEN undefined_object THEN           -- SQLSTATE 42704
            RAISE NOTICE
                '[0029_M9] pg_cron extension not installed in this PG instance. '
                'Archive schema created; pg_cron job skipped. '
                'Activate in production: install pg_cron and set '
                'shared_preload_libraries = ''pg_cron'' in postgresql.conf.';
        WHEN feature_not_supported THEN      -- SQLSTATE 0A000
            RAISE NOTICE
                '[0029_M9] pg_cron not loaded via shared_preload_libraries. '
                'Archive schema created; pg_cron job skipped.';
        WHEN undefined_file THEN             -- SQLSTATE 58P01
            RAISE NOTICE
                '[0029_M9] pg_cron shared library (.so) not found. '
                'Archive schema created; pg_cron job skipped.';
        WHEN OTHERS THEN
            _cron_available := FALSE;
            RAISE NOTICE
                '[0029_M9] CREATE EXTENSION pg_cron failed with unmapped error; '
                'archive schema created; pg_cron job skipped; migration continues.';
    END;

    -- -----------------------------------------------------------------------
    -- Step 4: register monthly archive job (idempotent: unschedule first)
    -- -----------------------------------------------------------------------
    IF _cron_available THEN
        BEGIN
            PERFORM cron.unschedule('audit_log_archive');
        EXCEPTION WHEN OTHERS THEN
            NULL;  -- job did not exist; safe to ignore
        END;

        -- Job body: copy rows older than 10 years to archive, then delete
        -- from source. The DELETE temporarily disables the immutability
        -- trigger on calc.audit_log (same pattern as 0028_M8 downgrade).
        -- Runs at 03:00 UTC on the 1st of every month.
        PERFORM cron.schedule(
            'audit_log_archive',
            '0 3 1 * *',
            $body$
            BEGIN;
            INSERT INTO calc_archive.audit_log_archive (
                id, tenant_id, correlation_id, occurred_at,
                user_id, user_role, action, resource, resource_id,
                request_method, request_path, status_code,
                ip_address, user_agent, before_state, after_state, extra
            )
            SELECT
                id, tenant_id, correlation_id, occurred_at,
                user_id, user_role, action, resource, resource_id,
                request_method, request_path, status_code,
                ip_address, user_agent, before_state, after_state, extra
            FROM calc.audit_log
            WHERE occurred_at < now() - INTERVAL '10 years';

            ALTER TABLE calc.audit_log DISABLE TRIGGER trg_audit_log_deny_mutation;
            DELETE FROM calc.audit_log WHERE occurred_at < now() - INTERVAL '10 years';
            ALTER TABLE calc.audit_log ENABLE TRIGGER trg_audit_log_deny_mutation;
            COMMIT;
            $body$
        );

        RAISE NOTICE
            '[0029_M9] pg_cron job ''audit_log_archive'' registered '
            '(runs at 03:00 UTC on the 1st of each month).';
    END IF;
END $$;
"""

# ---------------------------------------------------------------------------
# Downgrade block: unschedule job + drop archive schema CASCADE.
# ---------------------------------------------------------------------------
_DOWNGRADE_BLOCK = """\
DO $$
BEGIN
    -- Unschedule pg_cron job if pg_cron is present
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        BEGIN
            PERFORM cron.unschedule('audit_log_archive');
            RAISE NOTICE '[0029_M9 downgrade] pg_cron job ''audit_log_archive'' removed.';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE
                '[0029_M9 downgrade] pg_cron job ''audit_log_archive'' '
                'was not found — nothing to unschedule.';
        END;
    ELSE
        RAISE NOTICE
            '[0029_M9 downgrade] pg_cron extension not present; no job to unschedule.';
    END IF;

    -- Drop archive schema and all its objects
    DROP SCHEMA IF EXISTS calc_archive CASCADE;
    RAISE NOTICE '[0029_M9 downgrade] calc_archive schema dropped.';
END $$;
"""


def upgrade() -> None:
    """Create calc_archive schema + archive table; register pg_cron monthly job.

    Step-by-step:
      1. CREATE SCHEMA IF NOT EXISTS calc_archive.
      2. CREATE TABLE calc_archive.audit_log_archive (mirrors calc.audit_log,
         no immutability trigger, extra archived_at column).
      3. Try CREATE EXTENSION pg_cron (graceful NOTICE on failure).
      4. If pg_cron available: register job 'audit_log_archive' (0 3 1 * *).
    """
    op.get_bind().exec_driver_sql(_UPGRADE_BLOCK)


def downgrade() -> None:
    """Reverse M9: unschedule pg_cron job and drop calc_archive schema CASCADE.

    NOTE: rows already moved to calc_archive.audit_log_archive are NOT moved
    back to calc.audit_log — this would require a data reconciliation step
    that cannot be automated safely. Operators must decide case-by-case
    whether to restore archived data before running downgrade.
    """
    op.get_bind().exec_driver_sql(_DOWNGRADE_BLOCK)
