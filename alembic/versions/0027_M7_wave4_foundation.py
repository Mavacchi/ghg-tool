"""M7 — Wave 4 foundation: pg_cron extension + idempotency_keys scheduled cleanup.

Design decisions implemented in this migration
===============================================

1. pg_cron extension (Decision A)
   --------------------------------
   Attempts ``CREATE EXTENSION IF NOT EXISTS pg_cron`` inside a PL/pgSQL block
   that catches ``undefined_object`` (SQLSTATE 42704) and ``feature_not_supported``
   (SQLSTATE 0A000) to handle the two failure modes:

     a) The pg_cron shared library is not loaded — PG raises 0A000 with message
        "pg_cron must be loaded via shared_preload_libraries".
     b) The pg_cron package is not installed in the PG instance at all — the
        extension catalog row does not exist and PG raises 42704.

   In both cases the block emits a NOTICE and continues; the migration does NOT
   fail.  This allows the standard ``postgres:15-alpine`` testcontainers image
   (which does not include pg_cron) to run the full upgrade/downgrade cycle
   without modification.

   PRODUCTION NOTE: To activate pg_cron in a real deployment, add
       shared_preload_libraries = 'pg_cron'
   to postgresql.conf and restart PostgreSQL *before* running this migration.
   pg_cron is available in the bitnami/postgresql, TimescaleDB, and Amazon RDS
   PostgreSQL 15+ images out of the box; it requires a separate install on
   vanilla Debian/Ubuntu (apt install postgresql-15-cron).

2. cron.schedule — idempotency_keys_cleanup (Decision B)
   -------------------------------------------------------
   Registers a pg_cron job named ``idempotency_keys_cleanup`` that runs at
   minute 15 of every hour (cron expression: ``15 * * * *``) and issues:

       DELETE FROM cache.idempotency_keys WHERE expires_at < now();

   The job is created only when pg_cron is available.  Creation is idempotent:
   an existing job with the same name is unscheduled first.

   Rationale for pg_cron over app-side scheduler
   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
   App-side schedulers (APScheduler, Celery beat, Prefect schedules) require a
   long-running process to be online.  A PG-internal job fires even when all
   application replicas are down (maintenance windows, rolling deploys).  For a
   cache TTL cleanup, correctness requires that expired rows are purged regardless
   of application state.  pg_cron is the minimal-dependency solution for this.

   The migration degrades gracefully to a no-op on pg_cron-less environments; the
   app-side lookup (``WHERE expires_at > now()``, per migration 0026_M6) remains
   the authoritative gate for idempotency checking, so expired rows in the table
   are semantically inert even if the cleanup job never runs.

3. Service role for JWT auto-provisioning (Decision C)
   -----------------------------------------------------
   After migration 0025_M24, ref.roles contains: admin, editor, viewer.

   JWT auto-provisioning (SSO / OIDC users first seen in the system) will be
   assigned the ``viewer`` role by default at the application layer.  A separate
   ``service`` role is NOT required: service accounts authenticate with a shared
   application credential that is mapped to an existing role (typically ``admin``
   or ``editor``) by the infrastructure team during onboarding.

   Therefore, this migration makes NO changes to ref.roles.  This decision is
   documented here to prevent a future agent from adding a redundant role.

Revision ID : 0027_M7
Revises     : 0026_M6
Create Date : 2026-05-15
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0027_M7"
down_revision: str = "0026_M6"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# PL/pgSQL block that attempts to create pg_cron and, if successful, schedules
# the cleanup job.  Failures due to missing extension are caught and emitted as
# NOTICE so the block completes without error.
#
# SQLSTATE codes handled:
#   42704  undefined_object         — extension not present in the PG catalog
#   0A000  feature_not_supported    — pg_cron not in shared_preload_libraries
#   58P01  undefined_file           — .so file missing from filesystem (rare)
#   OTHERS catch-all                — CI containers may raise an unmapped
#                                     SQLSTATE; we log it and continue.
#
# The job unschedule + reschedule pattern makes the block idempotent: calling
# upgrade() twice produces the same final state (one job, current definition).
_PGCRON_SETUP_BLOCK = """\
DO $$
DECLARE
    _cron_available BOOLEAN := FALSE;
BEGIN
    -- Step 1: attempt to enable pg_cron.
    -- On testcontainers (postgres:15-alpine) this will raise an exception;
    -- we catch it and log a NOTICE rather than failing the migration.
    BEGIN
        CREATE EXTENSION IF NOT EXISTS pg_cron;
        _cron_available := TRUE;
    EXCEPTION
        WHEN undefined_object THEN           -- SQLSTATE 42704
            RAISE NOTICE
                '[0027_M7] pg_cron extension not installed in this PG instance. '
                'Skipping cron job registration. '
                'To activate in production: install pg_cron and set '
                'shared_preload_libraries = ''pg_cron'' in postgresql.conf.';
        WHEN feature_not_supported THEN      -- SQLSTATE 0A000
            RAISE NOTICE
                '[0027_M7] pg_cron is not loaded via shared_preload_libraries. '
                'Skipping cron job registration. '
                'To activate: add pg_cron to shared_preload_libraries and restart PG.';
        WHEN undefined_file THEN             -- SQLSTATE 58P01 (missing .so)
            RAISE NOTICE
                '[0027_M7] pg_cron shared library (.so) not found on the filesystem. '
                'Skipping cron job registration.';
        WHEN OTHERS THEN                     -- catch-all for CI containers
            -- Some PG containers (notably postgres:15-alpine in CI) raise a
            -- non-mapped SQLSTATE when CREATE EXTENSION fails because pg_cron
            -- is absent.  We catch everything else here, log the SQLSTATE and
            -- SQLERRM for postmortem, and continue with _cron_available := FALSE
            -- so the migration degrades gracefully instead of aborting the
            -- entire upgrade chain.
            _cron_available := FALSE;
            RAISE NOTICE
                '[0027_M7] CREATE EXTENSION pg_cron failed with unmapped error. '
                'SQLSTATE=%, SQLERRM=%. '
                'Skipping cron job registration; migration continues.',
                SQLSTATE, SQLERRM;
    END;

    -- Step 2: only proceed if extension creation succeeded.
    IF _cron_available THEN
        -- Make scheduling idempotent: remove any prior job with the same name
        -- before re-registering.  cron.unschedule() is a no-op if the job
        -- does not exist in pg_cron < 1.4; for 1.4+ use the name-based overload.
        BEGIN
            PERFORM cron.unschedule('idempotency_keys_cleanup');
        EXCEPTION WHEN OTHERS THEN
            -- unschedule raises if the job name does not exist in some versions;
            -- safe to ignore here since we are about to (re-)create it.
            NULL;
        END;

        -- Register the hourly cleanup job (minute 15 of every hour).
        -- The DELETE runs in the database that owns the pg_cron extension
        -- (cron.database_name GUC, defaults to the current DB on single-DB setups).
        PERFORM cron.schedule(
            'idempotency_keys_cleanup',
            '15 * * * *',
            $$DELETE FROM cache.idempotency_keys WHERE expires_at < now()$$
        );

        RAISE NOTICE
            '[0027_M7] pg_cron job ''idempotency_keys_cleanup'' registered '
            '(runs at :15 every hour, cleans cache.idempotency_keys).';
    END IF;
END $$;
"""

# Mirror teardown: unschedule the job (if pg_cron is present) and drop the
# extension only if this migration created it.  We do NOT drop pg_cron if it
# was already installed before M7 ran (there is no clean way to detect that
# from inside a PL/pgSQL block without a custom marker table, which would be
# over-engineering for an extension).  Therefore downgrade() only unschedules
# the job; the extension itself is left in place if it existed.
_PGCRON_TEARDOWN_BLOCK = """\
DO $$
BEGIN
    -- Only attempt cleanup if pg_cron is available.
    IF EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'pg_cron'
    ) THEN
        BEGIN
            PERFORM cron.unschedule('idempotency_keys_cleanup');
            RAISE NOTICE
                '[0027_M7 downgrade] pg_cron job ''idempotency_keys_cleanup'' removed.';
        EXCEPTION WHEN OTHERS THEN
            -- Job may not exist if upgrade() never registered it (e.g., after a
            -- failed partial run).  Log and continue.
            RAISE NOTICE
                '[0027_M7 downgrade] pg_cron job ''idempotency_keys_cleanup'' '
                'was not found — nothing to unschedule.';
        END;
    ELSE
        RAISE NOTICE
            '[0027_M7 downgrade] pg_cron extension not present; '
            'no cleanup job to unschedule.';
    END IF;
END $$;
"""


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Apply M7: pg_cron extension + idempotency_keys cleanup job.

    Step-by-step:
      1. Try to CREATE EXTENSION pg_cron.  Fail gracefully with NOTICE if
         pg_cron is not available in the target PG instance.
      2. If pg_cron was activated, register (or re-register) the hourly
         DELETE job on cache.idempotency_keys.

    No changes are made to ref.roles — see Decision C in the module docstring.
    """
    op.execute(_PGCRON_SETUP_BLOCK)


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Reverse M7: unschedule pg_cron cleanup job.

    The pg_cron extension itself is NOT dropped because:
      a) It may have been installed before this migration ran (impossible to
         distinguish without a custom sentinel).
      b) Dropping an extension can break other jobs registered by DBAs or
         other migrations.

    Only the specific job registered by this migration is removed.
    """
    op.execute(_PGCRON_TEARDOWN_BLOCK)
