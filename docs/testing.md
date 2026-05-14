# Testing guide

This document describes the test architecture for the GHG Accounting Tool,
explains the unit/integration split, and gives instructions for running
each tier locally and in CI.

---

## Test tiers

### Unit tests (`tests/unit/`)

Unit tests cover pure Python logic: emission-factor calculations, GWP
application, intensity metrics, Pydantic schema validation, ETL transforms,
and application-service orchestration.  All external dependencies
(database, HTTP) are mocked.

Run the unit suite:

```
pytest
```

The `addopts` in `pyproject.toml` defaults to `-m 'not integration'`, so a
plain `pytest` invocation always runs only the unit and property tests.

Coverage gate: 85% global, 100% on the `src/ghg_tool/calc` module.

### Property-based tests (`tests/property/`)

Property tests use Hypothesis to verify mathematical invariants: non-negativity
of emissions, linear scaling with consumption, GWP monotonicity, biogenic CO2
non-interference.  These run in the default `pytest` invocation.

### Integration tests -- env-var DB (`tests/integration/db/`, `tests/integration/api/`)

The pre-wave-4 integration tests target an already-running PostgreSQL instance
whose DSN is supplied via the `SQLALCHEMY_ASYNC_URL` environment variable.  They
are used by the `integration.yml` GitHub Actions workflow which provides a
`services: postgres:` block.

### Integration tests -- testcontainers (`tests/integration/postgres/`)

Wave-4 item #11 adds a second integration tier that uses
[testcontainers-python](https://github.com/testcontainers/testcontainers-python)
to spin up a fresh `postgres:15-alpine` container for each pytest session.

This tier tests:

- Alembic migration chain correctness (single head, no collisions, clean
  downgrade/upgrade round-trip).
- Append-only triggers actually rejecting UPDATE/DELETE on
  `calc.emissions_consolidated` and `ops.chart_annotations`.
- `ref.factor_catalog` post-publish immutability trigger.
- RLS policies enforcing tenant isolation across `calc.emissions_consolidated`
  and `ops.chart_annotations`.
- Bitemporal correction flow (`superseded_by` pointer via `fn_emit_correction`).
- NUMERIC(18,6) Decimal precision round-trips via the asyncpg cursor.

Run the testcontainers integration suite:

```
pytest -m integration tests/integration/postgres/
```

Requirements:

- Docker daemon must be running (Docker Desktop on macOS/Windows, Docker Engine
  on Linux).
- The `testcontainers[postgres]` package is installed as part of the `dev`
  extras: `pip install -e ".[dev]"`.

No environment variables are required: testcontainers allocates a random port
and manages credentials internally.

---

## Why testcontainers instead of a `services: postgres:` block

GitHub Actions `services:` blocks tie the Postgres lifecycle to a specific
YAML file.  This creates several problems:

1. **Local parity**: a developer running `pytest -m integration` locally has
   no `services:` block.  They must maintain a separate Docker Compose stack
   and keep its credentials in sync with the CI YAML.  testcontainers
   eliminates this: the same `pytest -m integration` command works identically
   everywhere Docker is available.

2. **Alembic targeting**: with a `services:` block the test process connects
   to an already-running Postgres that the Actions runner started independently.
   There is no guarantee the migration has run before the first test.  With
   testcontainers, the `migrated_db_url` session fixture calls
   `alembic.command.upgrade` against the exact container it created, so the
   schema is always present.

3. **No YAML drift**: the DSN used by `services:` is hard-coded in the workflow
   YAML and must stay in sync with env vars read by the test code.  Any
   mismatch produces a cryptic connection-refused error.  testcontainers
   exposes the DSN programmatically via `container.get_connection_url()`, so
   there is a single source of truth.

4. **Parallelism**: testcontainers supports running multiple containers in
   parallel (e.g. one per pytest-xdist worker), each with its own port.  A
   `services:` block is a single shared instance.

---

## Running tests in CI

### Unit tests (ci.yml)

The main CI workflow (`ci.yml`) runs lint, strict mypy, and the unit test
suite with a coverage gate.  No database is required.

### Testcontainers integration tests (integration-tests.yml)

The `integration-tests.yml` workflow triggers on pull requests and
`workflow_dispatch`.  It installs dev dependencies and runs:

```
pytest -m integration -v --tb=short --maxfail=3 tests/integration/postgres/
```

The Docker daemon is available on `ubuntu-latest` GHA runners without any
special configuration.

### Legacy env-var integration tests (integration.yml)

The existing `integration.yml` workflow continues to run the
`tests/integration/db/` and `tests/integration/api/` suites against a
`services: postgres:` container.  Both workflows are complementary and run
independently.

---

## Adding new integration tests

1. Place the test file under `tests/integration/postgres/`.
2. Mark the test with `@pytest.mark.integration` (or use the module-level
   `pytestmark = pytest.mark.integration`).
3. Use the session-scoped fixtures from `tests/integration/postgres/conftest.py`:
   - `async_engine`: asyncpg-backed engine pointing at the migrated container.
   - `async_session_factory`: sessionmaker for the same engine.
   - `db_session`: per-test session with automatic rollback (use for read-only
     or trigger-during-execute tests).
   - `seed_tenants`: returns `TenantSeed(tenant_a, tenant_b, user_a, user_b)`.
4. For tests that must commit (e.g. trigger-on-commit scenarios), use
   `async_engine.begin()` directly and TRUNCATE the affected tables in a
   `finally` block.
5. Never use f-string SQL; always use SQLAlchemy `text()` with named
   parameters.
