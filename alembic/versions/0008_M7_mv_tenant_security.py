"""M7 — Tenant-scoped security-barrier views over the materialised views.

SecurityAgent SEC-P0-002: ``calc.mv_kpi_summary`` and
``calc.mv_intensity_metrics`` (created in M5/M6) are independent relations in
PostgreSQL.  RLS on ``raw.*`` and on ``calc.emissions_consolidated`` does NOT
cascade into materialised views.  PostgreSQL 15/16 does not support
``ALTER MATERIALIZED VIEW ... ENABLE ROW LEVEL SECURITY`` (PG17+ only).

Fix: wrap each MV in a ``security_barrier`` view that filters rows by the
session GUC ``app.tenant_id`` — the same GUC plumbing M4 RLS depends on for
the underlying tables (set per-request by
``api/dependencies/session_guc.py`` → ``infrastructure/db/session.py``
``set_config('app.tenant_id', :tid, true)``).

Objects created
---------------
  calc.v_kpi_summary          — security_barrier=true view over calc.mv_kpi_summary
  calc.v_intensity_metrics    — security_barrier=true view over calc.mv_intensity_metrics

Permission changes
------------------
  Ensure the application DB role ``ghg_app`` exists (created NOLOGIN if
  missing — the role is normally provisioned by POSTGRES_USER in Docker,
  but the CI service container uses a different user so the GRANTs below
  would otherwise fail on a fresh CI database).
  GRANT SELECT on both views to the application DB role ``ghg_app``.
  REVOKE SELECT on the underlying MVs from ``ghg_app`` so that all
  application-path queries MUST go through the security-barrier views.

  NOTE: M4 uses RLS policies with ``current_setting()`` rather than
  named PostgreSQL roles for data_steward / esg_manager / auditor — those
  are application-layer RBAC codes stored in the JWT, not DB roles.  The
  single DB connection role is ``ghg_app`` (see
  ``infrastructure/db/session.py`` connection URL).  The MV refresh job
  runs under a privileged role (superuser / migration role) that bypasses
  the REVOKE, so background refresh is unaffected.

Action required from parallel backend-agent
-------------------------------------------
  After this migration lands, the following router changes MUST be applied:
    src/ghg_tool/api/routers/kpis.py:
        ``FROM calc.mv_kpi_summary`` → ``FROM calc.v_kpi_summary``
    src/ghg_tool/api/routers/intensity.py:
        ``FROM calc.mv_intensity_metrics`` → ``FROM calc.v_intensity_metrics``
  These files are intentionally NOT modified here (owned by backend-agent).

Idempotency
-----------
  ``CREATE OR REPLACE VIEW`` is inherently idempotent.
  ``GRANT`` / ``REVOKE`` are idempotent in PostgreSQL (no-op when already
  in the desired state).  Running ``alembic upgrade head`` twice is safe.

Revision: 0008_M7
Revises:  0007_M6
"""

from __future__ import annotations

from alembic import op

revision: str = "0008_M7"
down_revision: str = "0007_M6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create security-barrier views and lock down direct MV access."""

    # -------------------------------------------------------------------------
    # 1. Security-barrier view: calc.v_kpi_summary
    #
    # Wraps calc.mv_kpi_summary (created in M6) with a WHERE clause that
    # restricts rows to the tenant established by the session GUC.
    # ``current_setting('app.tenant_id', true)`` returns NULL rather than
    # raising an error when the GUC is not set (the second argument ``true``
    # is the ``missing_ok`` flag) — this is identical to the M4 RLS pattern.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE VIEW calc.v_kpi_summary
        WITH (security_barrier = true) AS
        SELECT *
        FROM calc.mv_kpi_summary
        WHERE tenant_id = current_setting('app.tenant_id', true)::uuid;
        """
    )

    # -------------------------------------------------------------------------
    # 2. Security-barrier view: calc.v_intensity_metrics
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE VIEW calc.v_intensity_metrics
        WITH (security_barrier = true) AS
        SELECT *
        FROM calc.mv_intensity_metrics
        WHERE tenant_id = current_setting('app.tenant_id', true)::uuid;
        """
    )

    # -------------------------------------------------------------------------
    # 3. Ensure the application DB role exists.
    #
    # In production the role is provisioned implicitly by the Postgres image
    # via POSTGRES_USER=ghg_app (see docker-compose.yml).  In CI the service
    # container uses POSTGRES_USER=ghg_test, so ``ghg_app`` does not exist
    # and the GRANTs below would fail with ``UndefinedObject: role "ghg_app"
    # does not exist``.  Create it idempotently as a NOLOGIN role: the
    # connecting user differs per environment, but the GRANT target name
    # must always resolve.  Existing roles (LOGIN, with password, owned by
    # POSTGRES_USER in Docker) are left untouched by ``IF NOT EXISTS``.
    # -------------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ghg_app') THEN
                CREATE ROLE ghg_app NOLOGIN;
            END IF;
        END
        $$;
        """
    )

    # -------------------------------------------------------------------------
    # 4. Grant SELECT on the new views to the application DB role.
    #
    # M4 uses RLS policies (not named DB roles) for data_steward / esg_manager
    # / auditor — those are JWT claim codes, not PostgreSQL role names.  The
    # single application DB role in session.py is ``ghg_app``.
    # -------------------------------------------------------------------------
    op.execute("GRANT SELECT ON calc.v_kpi_summary TO ghg_app;")
    op.execute("GRANT SELECT ON calc.v_intensity_metrics TO ghg_app;")

    # -------------------------------------------------------------------------
    # 5. Revoke direct MV access from the application role.
    #
    # Application paths MUST go through the security-barrier views.
    # The MV refresh job (ops.refresh_mv_kpi_summary / refresh_mv_intensity_metrics
    # / refresh_all_materialised_views) runs under a privileged migration/cron
    # role (superuser) that is not affected by this REVOKE.
    # -------------------------------------------------------------------------
    op.execute("REVOKE SELECT ON calc.mv_kpi_summary FROM ghg_app;")
    op.execute("REVOKE SELECT ON calc.mv_intensity_metrics FROM ghg_app;")


def downgrade() -> None:
    """Reverse M7 — restore state equivalent to end of M6.

    Order:
      1. Restore direct MV access for ghg_app.
      2. Drop the security-barrier views.
    """

    # -- 1. Re-grant direct MV access -----------------------------------------
    op.execute("GRANT SELECT ON calc.mv_kpi_summary TO ghg_app;")
    op.execute("GRANT SELECT ON calc.mv_intensity_metrics TO ghg_app;")

    # -- 2. Drop the security-barrier views ------------------------------------
    op.execute("DROP VIEW IF EXISTS calc.v_intensity_metrics;")
    op.execute("DROP VIEW IF EXISTS calc.v_kpi_summary;")
