"""Integration tests for migration 0026_M6: site_type, country, raw.direct_entry,
cache.idempotency_keys.

Validates decisions #1, #2, #6, #7 from auto_calc_design.md §12 (second round):
  - #7 site_type enum populated correctly for all 7 customer sites.
  - #2 country = 'IT' for all 7 sites; CHECK constraint rejects non-ISO-2.
  - #1 raw.direct_entry exists and is append-only (INSERT OK; UPDATE/DELETE blocked).
  - #6 cache.idempotency_keys exists; expires_at defaults to now() + 24h.

These tests require a real PostgreSQL 15 container.  They run via the shared
`async_engine` / `migrated_db_url` fixtures in tests/integration/postgres/conftest.py
(testcontainers-python, session-scoped).

Mark: pytest -m integration tests/integration/postgres/test_migration_0026.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Expected site_type backfill from auto_calc_design.md §12 #7
# Classification provided by customer 2026-05-15.
# ---------------------------------------------------------------------------

_EXPECTED_SITE_TYPES: dict[str, str] = {
    "IANO":          "STABILIMENTO_PRODUTTIVO",
    "VIANO":         "STABILIMENTO_PRODUTTIVO",
    "VIANO_GARGOLA": "MAGAZZINO",
    "CASALGRANDE":   "UFFICIO",
    "FIORANO":       "MAGAZZINO",
    "SASSUOLO":      "UFFICIO",
    "FRASSINORO":    "STABILIMENTO_PRODUTTIVO",
}

_ALL_SITE_CODES: list[str] = list(_EXPECTED_SITE_TYPES.keys())


# ===========================================================================
# Decision #7 — site_type
# ===========================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_site_type_column_exists_and_is_not_null(
    async_engine: AsyncEngine,
) -> None:
    """site_type column exists on ref.sites and has no NULL values.

    After M6 backfill + NOT NULL constraint, zero rows should have
    site_type IS NULL.
    """
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT count(*) FROM ref.sites WHERE site_type IS NULL"
            )
        )
        null_count = result.scalar_one()

    assert null_count == 0, (
        f"Expected 0 sites with NULL site_type after M6 backfill, found {null_count}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "codice_sito,expected_type",
    list(_EXPECTED_SITE_TYPES.items()),
    ids=list(_EXPECTED_SITE_TYPES.keys()),
)
async def test_site_type_backfill_per_site(
    async_engine: AsyncEngine,
    codice_sito: str,
    expected_type: str,
) -> None:
    """Each of the 7 customer sites carries the correct site_type value.

    The classification was provided by the customer on 2026-05-15:
      IANO, VIANO, FRASSINORO -> STABILIMENTO_PRODUTTIVO
      CASALGRANDE, SASSUOLO   -> UFFICIO
      VIANO_GARGOLA, FIORANO  -> MAGAZZINO

    Failure here means either the backfill UPDATE in 0026_M6 targeted the
    wrong codice_sito or the ENUM value was misspelled.
    """
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT site_type::text "
                "FROM ref.sites "
                "WHERE codice_sito = :site"
            ),
            {"site": codice_sito},
        )
        row = result.fetchone()

    assert row is not None, (
        f"Site '{codice_sito}' not found in ref.sites — "
        "ensure alembic upgrade head (M0 seed) has run"
    )
    assert row[0] == expected_type, (
        f"Site '{codice_sito}': expected site_type='{expected_type}', got '{row[0]}'"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_site_type_enum_rejects_invalid_value(
    async_engine: AsyncEngine,
) -> None:
    """INSERT with an invalid site_type value is rejected by the ENUM constraint.

    The ENUM ref.site_type_enum only accepts STABILIMENTO_PRODUTTIVO, UFFICIO,
    MAGAZZINO.  Any other string must raise an error at the DB level.
    """
    async with async_engine.connect() as conn:
        tenant_row = await conn.execute(
            text("SELECT id::text FROM ref.tenants LIMIT 1")
        )
        tenant_id = tenant_row.scalar_one()

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ref.sites "
                    "(tenant_id, codice_sito, full_name, role, geography, site_type) "
                    "VALUES "
                    "(CAST(:tid AS uuid), :code, :name, 'Test', 'Italy', "
                    " 'INVALID_TYPE'::ref.site_type_enum)"
                ),
                {
                    "tid": tenant_id,
                    "code": f"INVALID_SITE_{uuid.uuid4().hex[:6].upper()}",
                    "name": "Invalid site for enum test",
                },
            )


# ===========================================================================
# Decision #2 — country
# ===========================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_country_column_is_it_for_all_sites(
    async_engine: AsyncEngine,
) -> None:
    """All 7 customer sites have country = 'IT' after M6.

    The column was added with DEFAULT 'IT' and all existing sites are Italy
    (auto_calc_design.md §12 #2: "Tutti i 7 siti restano IT").
    """
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT s.codice_sito, s.country "
                "FROM ref.sites s "
                "JOIN ref.tenants t ON s.tenant_id = t.id "
                "WHERE t.code = 'CERAMIC_TILE_CO' "
                "  AND s.codice_sito = ANY(:sites) "
                "ORDER BY s.codice_sito"
            ),
            {"sites": _ALL_SITE_CODES},
        )
        rows = result.fetchall()

    assert len(rows) == len(_ALL_SITE_CODES), (
        f"Expected {len(_ALL_SITE_CODES)} sites, found {len(rows)}"
    )
    for codice_sito, country in rows:
        assert country == "IT", (
            f"Site '{codice_sito}': expected country='IT', got '{country}'"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_country_check_constraint_rejects_lowercase(
    async_engine: AsyncEngine,
) -> None:
    """CHECK constraint chk_sites_country_iso2 rejects lowercase country codes.

    The constraint is CHECK (country ~ '^[A-Z]{2}$') — ISO 3166-1 alpha-2 upper.
    'it' (lowercase) must be rejected.
    """
    async with async_engine.connect() as conn:
        tenant_row = await conn.execute(
            text("SELECT id::text FROM ref.tenants LIMIT 1")
        )
        tenant_id = tenant_row.scalar_one()

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ref.sites "
                    "(tenant_id, codice_sito, full_name, role, geography, "
                    " site_type, country) "
                    "VALUES "
                    "(CAST(:tid AS uuid), :code, :name, 'Test', 'Italy', "
                    " 'UFFICIO', 'it')"
                ),
                {
                    "tid": tenant_id,
                    "code": f"LOWER_COUNTRY_{uuid.uuid4().hex[:6].upper()}",
                    "name": "Lowercase country test site",
                },
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_country_check_constraint_rejects_three_chars(
    async_engine: AsyncEngine,
) -> None:
    """CHECK constraint rejects 3-character country codes (e.g. 'ITA').

    ISO 3166-1 alpha-2 is exactly 2 uppercase letters. 3-letter codes (alpha-3)
    must be rejected.
    """
    async with async_engine.connect() as conn:
        tenant_row = await conn.execute(
            text("SELECT id::text FROM ref.tenants LIMIT 1")
        )
        tenant_id = tenant_row.scalar_one()

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO ref.sites "
                    "(tenant_id, codice_sito, full_name, role, geography, "
                    " site_type, country) "
                    "VALUES "
                    "(CAST(:tid AS uuid), :code, :name, 'Test', 'Italy', "
                    " 'UFFICIO', 'ITA')"
                ),
                {
                    "tid": tenant_id,
                    "code": f"THREE_CHAR_CTRY_{uuid.uuid4().hex[:5].upper()}",
                    "name": "Three-char country test site",
                },
            )


# ===========================================================================
# Decision #1 — raw.direct_entry (append-only)
# ===========================================================================


async def _insert_direct_entry(
    engine: AsyncEngine,
    *,
    tenant_id: str,
    tco2e: float = 12.345678,
) -> str:
    """Commit one raw.direct_entry row; return its UUID.

    Uses engine.begin() so the row is visible outside the transaction — needed
    for subsequent UPDATE/DELETE trigger tests.

    Args:
        engine: AsyncEngine for the test database.
        tenant_id: UUID string of the tenant.
        tco2e: Emission value (must be >= 0).

    Returns:
        UUID string of the inserted row.
    """
    row_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO raw.direct_entry "
                "(id, tenant_id, correlation_id, inserted_by, "
                " request_payload, factor_id, factor_vintage, tco2e) "
                "VALUES "
                "(CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:corr AS uuid), "
                " :inserted_by, CAST(:payload AS jsonb), :factor_id, :vintage, :tco2e)"
            ),
            {
                "id": row_id,
                "tid": tenant_id,
                "corr": correlation_id,
                "inserted_by": "migration_test_runner",
                "payload": (
                    '{"scope": 1, "sub_scope": "combustion", '
                    '"codice_sito": "IANO", "anno": 2024, '
                    '"quantita": "100.0", "unita": "Sm3"}'
                ),
                "factor_id": "COMB_GAS_NAT_CO2_DEFRA_2024",
                "vintage": 2024,
                "tco2e": tco2e,
            },
        )
    return row_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_entry_table_exists(
    async_engine: AsyncEngine,
) -> None:
    """raw.direct_entry table exists and is queryable after M6."""
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'raw' AND table_name = 'direct_entry'"
            )
        )
        count = result.scalar_one()

    assert count == 1, (
        "raw.direct_entry must exist after migration 0026_M6; "
        "ensure alembic upgrade head has been run"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_entry_insert_succeeds(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """A valid INSERT into raw.direct_entry commits without error (positive case).

    Verifies that the table accepts the expected columns and that tco2e is
    stored as NUMERIC (positive, round-trips correctly).
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    inserted_tco2e = Decimal("12.345678")

    row_id = await _insert_direct_entry(
        async_engine,
        tenant_id=seed.tenant_a,
        tco2e=float(inserted_tco2e),
    )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id::text, tco2e "
                "FROM raw.direct_entry "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        row = result.fetchone()

    assert row is not None, f"Inserted direct_entry row {row_id} must be readable"
    assert str(row[0]) == row_id
    returned = Decimal(str(row[1]))
    assert abs(returned - inserted_tco2e) < Decimal("0.000001"), (
        f"tco2e precision lost: inserted {inserted_tco2e}, got {returned}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_entry_negative_tco2e_rejected(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """raw.direct_entry CHECK (tco2e >= 0) rejects negative emission values."""
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
        await _insert_direct_entry(
            async_engine,
            tenant_id=seed.tenant_a,
            tco2e=-1.0,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_entry_update_rejected_by_trigger(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """UPDATE on raw.direct_entry is rejected by the ops.deny_mutation() trigger.

    The trg_raw_direct_entry_deny_mutation trigger (added in M6) must fire
    BEFORE UPDATE and raise PG exception P0001 with 'forbidden' in the message.
    The row must remain unchanged after the rejected UPDATE.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id = await _insert_direct_entry(
        async_engine,
        tenant_id=seed.tenant_a,
        tco2e=5.0,
    )

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE raw.direct_entry "
                    "SET tco2e = 999.0 "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            )

    err_str = str(exc_info.value).lower()
    assert "forbidden" in err_str or "mutation" in err_str or "p0001" in err_str, (
        f"Expected append-only guard message, got: {exc_info.value}"
    )

    # Verify original value is unchanged
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tco2e FROM raw.direct_entry "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        row = result.fetchone()

    assert row is not None, "Row must still exist after rejected UPDATE"
    assert abs(float(row[0]) - 5.0) < 1e-4, (
        f"tco2e must remain 5.0 after rejected UPDATE, got {row[0]}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_entry_delete_rejected_by_trigger(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """DELETE on raw.direct_entry is rejected by the ops.deny_mutation() trigger.

    The trigger must fire unconditionally on DELETE.  The row must survive
    the rejected DELETE.
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    row_id = await _insert_direct_entry(
        async_engine,
        tenant_id=seed.tenant_a,
        tco2e=7.5,
    )

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as exc_info:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM raw.direct_entry "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            )

    err_str = str(exc_info.value).lower()
    assert "forbidden" in err_str or "mutation" in err_str or "p0001" in err_str, (
        f"Expected append-only guard message, got: {exc_info.value}"
    )

    # Row must still exist
    async with async_engine.connect() as conn:
        count_row = await conn.execute(
            text(
                "SELECT count(*) FROM raw.direct_entry "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": row_id},
        )
        assert count_row.scalar_one() == 1, "Row must survive rejected DELETE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_entry_correlation_id_index_exists(
    async_engine: AsyncEngine,
) -> None:
    """idx_direct_entry_corr index exists on raw.direct_entry(correlation_id)."""
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'raw' "
                "  AND tablename  = 'direct_entry' "
                "  AND indexname  = 'idx_direct_entry_corr'"
            )
        )
        row = result.fetchone()

    assert row is not None, (
        "Index idx_direct_entry_corr must exist on raw.direct_entry — "
        "check 0026_M6 upgrade()"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_entry_tenant_inserted_index_exists(
    async_engine: AsyncEngine,
) -> None:
    """idx_direct_entry_tenant_inserted index exists on raw.direct_entry."""
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'raw' "
                "  AND tablename  = 'direct_entry' "
                "  AND indexname  = 'idx_direct_entry_tenant_inserted'"
            )
        )
        row = result.fetchone()

    assert row is not None, (
        "Index idx_direct_entry_tenant_inserted must exist on raw.direct_entry"
    )


# ===========================================================================
# Decision #6 — cache.idempotency_keys
# ===========================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_keys_table_exists(
    async_engine: AsyncEngine,
) -> None:
    """cache.idempotency_keys table exists after M6."""
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'cache' AND table_name = 'idempotency_keys'"
            )
        )
        count = result.scalar_one()

    assert count == 1, (
        "cache.idempotency_keys must exist after migration 0026_M6"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_keys_insert_succeeds(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """A valid INSERT into cache.idempotency_keys commits without error."""
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    idem_key = f"test-idempotency-{uuid.uuid4().hex}"

    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO cache.idempotency_keys "
                "(key, tenant_id, endpoint, request_hash, "
                " response_status, response_body) "
                "VALUES "
                "(:key, CAST(:tid AS uuid), :endpoint, :req_hash, "
                " :status, CAST(:body AS jsonb))"
            ),
            {
                "key": idem_key,
                "tid": seed.tenant_a,
                "endpoint": "POST /api/v1/calc/insert",
                "req_hash": "a" * 64,  # 64-char SHA-256 hex placeholder
                "status": 201,
                "body": '{"emission_id": "some-uuid"}',
            },
        )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT key, response_status "
                "FROM cache.idempotency_keys "
                "WHERE key = :key"
            ),
            {"key": idem_key},
        )
        row = result.fetchone()

    assert row is not None, f"Inserted idempotency key '{idem_key}' must be readable"
    assert row[0] == idem_key
    assert row[1] == 201


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_keys_expires_at_defaults_to_24h(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """expires_at column defaults to now() + INTERVAL '24 hours'.

    Verifies decision #6 TTL: the idempotency key must expire exactly 24 h
    after insertion (within a 30-second tolerance for test execution time).
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    idem_key = f"test-expires-at-{uuid.uuid4().hex}"

    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO cache.idempotency_keys "
                "(key, tenant_id, endpoint, request_hash, "
                " response_status, response_body) "
                "VALUES "
                "(:key, CAST(:tid AS uuid), :endpoint, :req_hash, "
                " :status, CAST(:body AS jsonb))"
            ),
            {
                "key": idem_key,
                "tid": seed.tenant_a,
                "endpoint": "POST /api/v1/calc/insert",
                "req_hash": "b" * 64,
                "status": 201,
                "body": '{"emission_id": "other-uuid"}',
            },
        )

    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT "
                "  EXTRACT(EPOCH FROM (expires_at - created_at)) AS delta_seconds "
                "FROM cache.idempotency_keys "
                "WHERE key = :key"
            ),
            {"key": idem_key},
        )
        delta_seconds = result.scalar_one()

    # 24 hours = 86400 seconds; allow ±30 s for test execution drift.
    assert abs(float(delta_seconds) - 86400.0) < 30.0, (
        f"expires_at must be ~now() + 24h (86400 s); "
        f"actual delta from created_at = {delta_seconds:.1f} s"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_keys_primary_key_unique(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """Duplicate idempotency key raises a unique violation (PRIMARY KEY on key)."""
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]
    idem_key = f"test-pk-unique-{uuid.uuid4().hex}"

    # First insert — must succeed
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO cache.idempotency_keys "
                "(key, tenant_id, endpoint, request_hash, "
                " response_status, response_body) "
                "VALUES "
                "(:key, CAST(:tid AS uuid), :endpoint, :req_hash, "
                " :status, CAST(:body AS jsonb))"
            ),
            {
                "key": idem_key,
                "tid": seed.tenant_a,
                "endpoint": "POST /api/v1/calc/insert",
                "req_hash": "c" * 64,
                "status": 201,
                "body": '{"emission_id": "first-uuid"}',
            },
        )

    # Second insert with the same key — must fail
    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO cache.idempotency_keys "
                    "(key, tenant_id, endpoint, request_hash, "
                    " response_status, response_body) "
                    "VALUES "
                    "(:key, CAST(:tid AS uuid), :endpoint, :req_hash, "
                    " :status, CAST(:body AS jsonb))"
                ),
                {
                    "key": idem_key,
                    "tid": seed.tenant_a,
                    "endpoint": "POST /api/v1/calc/insert",
                    "req_hash": "d" * 64,
                    "status": 201,
                    "body": '{"emission_id": "duplicate-uuid"}',
                },
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_keys_expires_index_exists(
    async_engine: AsyncEngine,
) -> None:
    """idx_idempotency_expires index exists on cache.idempotency_keys(expires_at)."""
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'cache' "
                "  AND tablename  = 'idempotency_keys' "
                "  AND indexname  = 'idx_idempotency_expires'"
            )
        )
        row = result.fetchone()

    assert row is not None, (
        "Index idx_idempotency_expires must exist on cache.idempotency_keys(expires_at)"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idempotency_keys_app_side_lookup_pattern(
    async_engine: AsyncEngine,
    seed_tenants: object,
) -> None:
    """App-side lookup WHERE key = $1 AND expires_at > now() works correctly.

    Verifies that a freshly inserted key IS visible through the app-side
    lookup pattern (expires_at > now()), while a key with a past expires_at
    is NOT visible.

    This is the exact pattern used by the backend IdempotencyKeyRepository
    per design doc §12 #6 ("App-side lookup: WHERE expires_at > now()").
    """
    from tests.integration.postgres.conftest import TenantSeed  # noqa: PLC0415

    seed: TenantSeed = seed_tenants  # type: ignore[assignment]

    fresh_key = f"test-fresh-{uuid.uuid4().hex}"
    expired_key = f"test-expired-{uuid.uuid4().hex}"

    async with async_engine.begin() as conn:
        # Fresh key: default expires_at = now() + 24h (still valid)
        await conn.execute(
            text(
                "INSERT INTO cache.idempotency_keys "
                "(key, tenant_id, endpoint, request_hash, "
                " response_status, response_body) "
                "VALUES "
                "(:key, CAST(:tid AS uuid), :endpoint, :req_hash, "
                " :status, CAST(:body AS jsonb))"
            ),
            {
                "key": fresh_key,
                "tid": seed.tenant_a,
                "endpoint": "POST /api/v1/calc/insert",
                "req_hash": "e" * 64,
                "status": 201,
                "body": '{"emission_id": "fresh"}',
            },
        )
        # Expired key: explicitly set expires_at in the past
        await conn.execute(
            text(
                "INSERT INTO cache.idempotency_keys "
                "(key, tenant_id, endpoint, request_hash, "
                " response_status, response_body, expires_at) "
                "VALUES "
                "(:key, CAST(:tid AS uuid), :endpoint, :req_hash, "
                " :status, CAST(:body AS jsonb), now() - INTERVAL '1 second')"
            ),
            {
                "key": expired_key,
                "tid": seed.tenant_a,
                "endpoint": "POST /api/v1/calc/insert",
                "req_hash": "f" * 64,
                "status": 201,
                "body": '{"emission_id": "expired"}',
            },
        )

    async with async_engine.connect() as conn:
        # Fresh key must appear in the app-side lookup
        fresh_result = await conn.execute(
            text(
                "SELECT key FROM cache.idempotency_keys "
                "WHERE key = :key AND expires_at > now()"
            ),
            {"key": fresh_key},
        )
        fresh_row = fresh_result.fetchone()

        # Expired key must NOT appear
        expired_result = await conn.execute(
            text(
                "SELECT key FROM cache.idempotency_keys "
                "WHERE key = :key AND expires_at > now()"
            ),
            {"key": expired_key},
        )
        expired_row = expired_result.fetchone()

    assert fresh_row is not None, (
        f"Fresh key '{fresh_key}' must be returned by app-side lookup (expires_at > now())"
    )
    assert expired_row is None, (
        f"Expired key '{expired_key}' must NOT be returned by app-side lookup"
    )
