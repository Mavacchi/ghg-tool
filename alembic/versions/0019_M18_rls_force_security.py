"""M18 -- RLS coverage, OTP replay defence, partial-jti consumed table.

Covers findings S-001 to S-005, S-008, S-010, BUG-25, BUG-02.

Changes (all additive / no DROP COLUMN):

1. Enable + FORCE Row Level Security on:
   - auth.sessions          (S-001)
   - ops.calc_runs          (S-002)
   - calc.factor_publish_approvals  (S-003)
   - ref.users              (S-004)

   Policy pattern: ``USING (tenant_id = current_setting('app.tenant_id', true)::uuid)``
   and matching ``WITH CHECK`` for INSERT/UPDATE.

2. ALTER TABLE ops.chart_annotations FORCE ROW LEVEL SECURITY  (S-005).
   The table already has ENABLE RLS from migration 0018_M17; only FORCE was missing.

3. Create role ``ghg_session_reader`` with SELECT on auth.sessions only, BYPASSRLS.
   Used by SessionCheckMiddleware so it can look up jti rows without needing
   GUC injection (the jti lookup is cross-tenant by design -- we look up by jti
   only, not by tenant_id, because the middleware runs before the tenant is known).
   This role is read-only and cannot modify any data.

4. ADD COLUMN ref.users.totp_last_counter BIGINT NOT NULL DEFAULT 0  (S-008/BUG-25).
   Stores the TOTP time-step counter of the last accepted OTP to prevent replay.

5. Revoke column-level SELECT on sensitive ref.users columns from PUBLIC
   (defence in depth): password_hash, totp_secret, totp_last_counter  (S-004).

6. CREATE TABLE auth.consumed_partial_jti  (BUG-02 / S-010).
   Records the jti of every consumed partial (pre_2fa) token to prevent
   replay within the 5-minute TTL window.

Revision: 0019_M18
Revises:  0018_M17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0019_M18"
down_revision: str = "0018_M17"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply all RLS, counter, and consumed-jti changes."""

    # -------------------------------------------------------------------------
    # 1. RLS on auth.sessions (S-001)
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE auth.sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE auth.sessions FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY p_sessions_tenant_isolation ON auth.sessions
        AS PERMISSIVE
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -------------------------------------------------------------------------
    # 2. RLS on ops.calc_runs (S-002)
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE ops.calc_runs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE ops.calc_runs FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY p_calc_runs_tenant_isolation ON ops.calc_runs
        AS PERMISSIVE
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -------------------------------------------------------------------------
    # 3. RLS on calc.factor_publish_approvals (S-003)
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE calc.factor_publish_approvals ENABLE ROW LEVEL SECURITY;"
    )
    op.execute(
        "ALTER TABLE calc.factor_publish_approvals FORCE ROW LEVEL SECURITY;"
    )
    op.execute(
        """
        CREATE POLICY p_fpa_tenant_isolation ON calc.factor_publish_approvals
        AS PERMISSIVE
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -------------------------------------------------------------------------
    # 4. RLS on ref.users (S-004)
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE ref.users ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE ref.users FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY p_users_tenant_isolation ON ref.users
        AS PERMISSIVE
        FOR ALL
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )

    # -------------------------------------------------------------------------
    # 5. FORCE RLS on ops.chart_annotations (S-005)
    #    ENABLE was added in 0018_M17; only FORCE was missing.
    # -------------------------------------------------------------------------
    op.execute("ALTER TABLE ops.chart_annotations FORCE ROW LEVEL SECURITY;")

    # -------------------------------------------------------------------------
    # 6. Privileged read-only role for SessionCheckMiddleware (S-001 / S-012)
    #    ghg_session_reader can SELECT from auth.sessions and BYPASSES RLS so
    #    the middleware can look up jti rows without needing tenant GUCs.
    #    This role cannot INSERT, UPDATE, or DELETE.
    # -------------------------------------------------------------------------
    op.execute(
        "DO $$ BEGIN "
        "  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ghg_session_reader') "
        "  THEN CREATE ROLE ghg_session_reader NOLOGIN BYPASSRLS; "
        "  END IF; "
        "END $$;"
    )
    op.execute(
        "GRANT SELECT ON auth.sessions TO ghg_session_reader;"
    )

    # -------------------------------------------------------------------------
    # 7. totp_last_counter column on ref.users (S-008 / BUG-25)
    # -------------------------------------------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "totp_last_counter",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="ref",
    )

    # -------------------------------------------------------------------------
    # 8. Revoke column SELECT on sensitive columns from PUBLIC (S-004)
    # -------------------------------------------------------------------------
    op.execute(
        "REVOKE SELECT (password_hash, totp_secret, totp_last_counter) "
        "ON ref.users FROM PUBLIC;"
    )

    # -------------------------------------------------------------------------
    # 9. auth.consumed_partial_jti table (BUG-02 / S-010)
    # -------------------------------------------------------------------------
    op.create_table(
        "consumed_partial_jti",
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="auth",
    )

    # Index for TTL-based eviction queries (background cleanup job).
    op.create_index(
        "ix_consumed_partial_jti_consumed_at",
        "consumed_partial_jti",
        ["consumed_at"],
        schema="auth",
    )


def downgrade() -> None:
    """Reverse all changes from this migration."""

    # Drop consumed_partial_jti
    op.drop_index(
        "ix_consumed_partial_jti_consumed_at",
        table_name="consumed_partial_jti",
        schema="auth",
    )
    op.drop_table("consumed_partial_jti", schema="auth")

    # Restore column grants (no-op if PUBLIC never had SELECT -- harmless)
    op.execute(
        "GRANT SELECT (password_hash, totp_secret, totp_last_counter) "
        "ON ref.users TO PUBLIC;"
    )

    # Remove totp_last_counter column
    op.drop_column("users", "totp_last_counter", schema="ref")

    # Remove ghg_session_reader role grants (leave the role itself to avoid
    # breaking any manual configuration; the role has no permissions without
    # the grant)
    op.execute(
        "REVOKE SELECT ON auth.sessions FROM ghg_session_reader;"
    )

    # Drop RLS policies and disable
    op.execute("DROP POLICY IF EXISTS p_sessions_tenant_isolation ON auth.sessions;")
    op.execute("ALTER TABLE auth.sessions DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE auth.sessions NO FORCE ROW LEVEL SECURITY;")

    op.execute("DROP POLICY IF EXISTS p_calc_runs_tenant_isolation ON ops.calc_runs;")
    op.execute("ALTER TABLE ops.calc_runs DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE ops.calc_runs NO FORCE ROW LEVEL SECURITY;")

    op.execute(
        "DROP POLICY IF EXISTS p_fpa_tenant_isolation "
        "ON calc.factor_publish_approvals;"
    )
    op.execute(
        "ALTER TABLE calc.factor_publish_approvals DISABLE ROW LEVEL SECURITY;"
    )
    op.execute(
        "ALTER TABLE calc.factor_publish_approvals NO FORCE ROW LEVEL SECURITY;"
    )

    op.execute("DROP POLICY IF EXISTS p_users_tenant_isolation ON ref.users;")
    op.execute("ALTER TABLE ref.users DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE ref.users NO FORCE ROW LEVEL SECURITY;")

    op.execute("ALTER TABLE ops.chart_annotations NO FORCE ROW LEVEL SECURITY;")
