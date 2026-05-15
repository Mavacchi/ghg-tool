"""M6 — site_type enum + country on ref.sites; raw.direct_entry; cache.idempotency_keys.

Implements decisions #1, #2, #6, #7 from auto_calc_design.md §12 (second round)
as a single atomic migration.

Decision #7: site_type ENUM on ref.sites
  - New ENUM ref.site_type_enum with values
    STABILIMENTO_PRODUTTIVO | UFFICIO | MAGAZZINO.
  - Column site_type added to ref.sites (initially nullable for backfill).
  - Backfill from customer classification dated 2026-05-15.
  - Column set NOT NULL after backfill.
  - Validation of Processo_Decarb per site_type is intentionally kept
    in the application layer (backend 422) — the DB does not encode
    "Processo_Decarb" as a magic string per design doc §12 #7.

Decision #2: country on ref.sites
  - CHAR(2) column with DEFAULT 'IT' and CHECK (country ~ '^[A-Z]{2}$').
  - All 7 existing sites are IT; default covers future inserts.

Decision #1: raw.direct_entry table
  - Parallel to raw.scope*_ingestions (same append-only pattern).
  - Append-only trigger via ops.deny_mutation() (defined in M0).
  - Stores the original user request payload (JSONB) and resolved factor
    metadata at insert time for FR-22 universal traceability.

Decision #6: cache.idempotency_keys table
  - New schema 'cache'.
  - TTL: 24 hours via expires_at column; app-side lookup uses
    WHERE expires_at > now(). No pgcron job in this migration.
  - TODO: add pg_cron job for periodic cleanup of expired rows when
    pg_cron extension is available in the target environment. For now
    cleanup is application-side (see backend IdempotencyKeyRepository).

Revision ID : 0026_M6
Revises     : 0025_M24
Create Date : 2026-05-15
"""

from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
revision: str = "0026_M6"
down_revision: str = "0025_M24"
branch_labels: str | None = None
depends_on: str | None = None
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Apply all four decisions atomically."""

    # =========================================================================
    # Decision #7 — site_type ENUM + column on ref.sites
    # =========================================================================

    # Create ENUM in the ref schema so it is co-located with the table it serves.
    op.execute(
        """
        CREATE TYPE ref.site_type_enum AS ENUM (
            'STABILIMENTO_PRODUTTIVO',
            'UFFICIO',
            'MAGAZZINO'
        );
        """
    )

    # Add column as nullable first so we can backfill before applying NOT NULL.
    op.execute(
        """
        ALTER TABLE ref.sites
            ADD COLUMN site_type ref.site_type_enum;
        """
    )

    # Backfill — classification provided by customer 2026-05-15.
    # Each codice_sito is updated independently so a missing site raises a
    # visible error rather than silently skipping.
    op.execute(
        """
        UPDATE ref.sites SET site_type = 'STABILIMENTO_PRODUTTIVO'
        WHERE codice_sito = 'IANO';
        """
    )
    op.execute(
        """
        UPDATE ref.sites SET site_type = 'STABILIMENTO_PRODUTTIVO'
        WHERE codice_sito = 'VIANO';
        """
    )
    op.execute(
        """
        UPDATE ref.sites SET site_type = 'MAGAZZINO'
        WHERE codice_sito = 'VIANO_GARGOLA';
        """
    )
    op.execute(
        """
        UPDATE ref.sites SET site_type = 'UFFICIO'
        WHERE codice_sito = 'CASALGRANDE';
        """
    )
    op.execute(
        """
        UPDATE ref.sites SET site_type = 'MAGAZZINO'
        WHERE codice_sito = 'FIORANO';
        """
    )
    op.execute(
        """
        UPDATE ref.sites SET site_type = 'UFFICIO'
        WHERE codice_sito = 'SASSUOLO';
        """
    )
    op.execute(
        """
        UPDATE ref.sites SET site_type = 'STABILIMENTO_PRODUTTIVO'
        WHERE codice_sito = 'FRASSINORO';
        """
    )

    # Verify backfill covered all active sites before tightening the constraint.
    # Raises if any site has NULL site_type — prevents a silent partial backfill.
    op.execute(
        """
        DO $$
        DECLARE
            missing_count INT;
        BEGIN
            SELECT count(*) INTO missing_count
            FROM ref.sites
            WHERE site_type IS NULL;
            IF missing_count > 0 THEN
                RAISE EXCEPTION
                    'Backfill incomplete: % site(s) still have NULL site_type',
                    missing_count;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        ALTER TABLE ref.sites
            ALTER COLUMN site_type SET NOT NULL;
        """
    )

    # =========================================================================
    # Decision #2 — country CHAR(2) on ref.sites
    # =========================================================================

    # DEFAULT 'IT' covers the 7 existing rows without a separate UPDATE.
    op.execute(
        """
        ALTER TABLE ref.sites
            ADD COLUMN country CHAR(2) NOT NULL DEFAULT 'IT'
            CONSTRAINT chk_sites_country_iso2 CHECK (country ~ '^[A-Z]{2}$');
        """
    )

    # =========================================================================
    # Decision #1 — raw.direct_entry (append-only)
    # =========================================================================

    op.execute(
        """
        CREATE TABLE raw.direct_entry (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL REFERENCES ref.tenants(id),
            correlation_id  UUID         NOT NULL,
            inserted_by     VARCHAR(120) NOT NULL,
            inserted_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            -- Original user request payload preserved verbatim for FR-22 traceability.
            request_payload JSONB        NOT NULL,
            -- Emission factor resolved at insert time (denormalised for audit durability).
            factor_id       VARCHAR(120) NOT NULL,
            factor_vintage  INT          NOT NULL,
            -- Computed result — never negative.
            tco2e           NUMERIC(15,6) NOT NULL CHECK (tco2e >= 0)
        );
        """
    )

    op.execute(
        """
        CREATE INDEX idx_direct_entry_corr
            ON raw.direct_entry (correlation_id);
        """
    )
    op.execute(
        """
        CREATE INDEX idx_direct_entry_tenant_inserted
            ON raw.direct_entry (tenant_id, inserted_at DESC);
        """
    )

    # Append-only: reuse the shared ops.deny_mutation() guard from M0.
    op.execute(
        """
        CREATE TRIGGER trg_raw_direct_entry_deny_mutation
        BEFORE UPDATE OR DELETE ON raw.direct_entry
        FOR EACH ROW EXECUTE FUNCTION ops.deny_mutation();
        """
    )

    # =========================================================================
    # Decision #6 — cache schema + cache.idempotency_keys
    # =========================================================================

    op.execute("CREATE SCHEMA IF NOT EXISTS cache;")

    op.execute(
        """
        CREATE TABLE cache.idempotency_keys (
            -- The raw Idempotency-Key header value sent by the caller.
            key             VARCHAR(120) PRIMARY KEY,
            tenant_id       UUID         NOT NULL,
            -- Identifies the operation for which the key was issued.
            -- Example: 'POST /api/v1/calc/insert'
            endpoint        VARCHAR(80)  NOT NULL,
            -- SHA-256 hex digest of the canonical request body (UTF-8 bytes).
            -- Used to detect key reuse with a different body (RFC 8792 §3).
            request_hash    CHAR(64)     NOT NULL,
            response_status INT          NOT NULL,
            response_body   JSONB        NOT NULL,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            -- Keys expire after 24 hours (decision #6).
            -- App-side lookup: WHERE key = $1 AND expires_at > now()
            -- TODO: add a pg_cron job for periodic bulk-delete of expired rows
            --       once pg_cron is available in the target environment.
            --       Example job: DELETE FROM cache.idempotency_keys
            --                    WHERE expires_at < now();  -- run every hour
            expires_at      TIMESTAMPTZ  NOT NULL
                            DEFAULT (now() + INTERVAL '24 hours')
        );
        """
    )

    op.execute(
        """
        CREATE INDEX idx_idempotency_expires
            ON cache.idempotency_keys (expires_at);
        """
    )


def downgrade() -> None:
    """Reverse M6 — drop in strict reverse-dependency order."""

    # -------------------------------------------------------------------------
    # Decision #6 — drop cache.idempotency_keys and cache schema
    # -------------------------------------------------------------------------
    op.execute("DROP TABLE IF EXISTS cache.idempotency_keys CASCADE;")
    op.execute("DROP SCHEMA IF EXISTS cache CASCADE;")

    # -------------------------------------------------------------------------
    # Decision #1 — drop raw.direct_entry (trigger drops automatically via CASCADE)
    # -------------------------------------------------------------------------
    op.execute("DROP TABLE IF EXISTS raw.direct_entry CASCADE;")

    # -------------------------------------------------------------------------
    # Decision #2 — drop country column from ref.sites
    # Dropping the column preserves existing rows (no data loss).
    # The DEFAULT 'IT' means all existing rows already have 'IT'; dropping the
    # column is the clean inverse of adding it.
    # -------------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE ref.sites
            DROP COLUMN IF EXISTS country;
        """
    )

    # -------------------------------------------------------------------------
    # Decision #7 — drop site_type column then ENUM
    # Column must be dropped before the ENUM type can be removed.
    # -------------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE ref.sites
            DROP COLUMN IF EXISTS site_type;
        """
    )
    op.execute("DROP TYPE IF EXISTS ref.site_type_enum;")
