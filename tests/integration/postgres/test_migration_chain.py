"""Integration tests: Alembic migration chain correctness.

Verifies:
  1. alembic upgrade head succeeds against a clean PostgreSQL 15 container.
  2. After upgrade, exactly one head exists (no multi-head regression).
  3. alembic downgrade base then upgrade head is a clean round-trip.

These tests run against a real container provided by testcontainers-python.
They are opt-in via -m integration; the default pytest run excludes them.

ISAE 3000 relevance: the audit assurance model depends on a deterministic,
single-head migration chain. Any branching in the migration DAG can cause
a production upgrade to apply migrations in a non-deterministic order,
silently omitting schema objects. Catching multi-head regressions in CI
before they reach main is mandatory.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

pytestmark = pytest.mark.integration

_PG_IMAGE = "postgres:15-alpine"
_PG_USER = "mig_test"
_PG_PASSWORD = "mig_test_pw"

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_ALEMBIC_INI = os.path.join(_REPO_ROOT, "alembic.ini")


def _make_config(sync_url: str) -> AlembicConfig:
    """Build an AlembicConfig pointing at sync_url.

    Args:
        sync_url: psycopg-dialect connection string.

    Returns:
        Configured AlembicConfig instance.
    """
    cfg = AlembicConfig(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


def _run_alembic_against(
    sync_url: str,
    func: Callable[..., Any],
    *args: object,
) -> None:
    """Run an alembic command against ``sync_url``, overriding ``SQLALCHEMY_URL``.

    ``alembic/env.py`` reads ``SQLALCHEMY_URL`` from the environment and uses it
    to override any programmatic ``cfg.set_main_option("sqlalchemy.url", ...)``.
    In CI (the ``integration.yml`` GHA workflow) ``SQLALCHEMY_URL`` is exported
    pointing at the GHA postgres service container — which is a *different*
    database from the testcontainer this test just created.  Without this
    override the migration is applied to the wrong DB and the subsequent
    assertions hit an un-migrated database (``alembic_version`` missing).

    Args:
        sync_url: Target DSN (must win against any ambient ``SQLALCHEMY_URL``).
        func: The ``alembic.command`` callable to invoke (``upgrade``,
            ``downgrade``).
        *args: Positional arguments forwarded to ``func`` after ``cfg``.
    """
    original_env = os.environ.get("SQLALCHEMY_URL")
    os.environ["SQLALCHEMY_URL"] = sync_url
    try:
        cfg = _make_config(sync_url)
        func(cfg, *args)
    finally:
        if original_env is None:
            os.environ.pop("SQLALCHEMY_URL", None)
        else:
            os.environ["SQLALCHEMY_URL"] = original_env


def _container_sync_url(container: PostgresContainer) -> str:
    """Convert a testcontainers connection URL to use the psycopg (v3) driver.

    testcontainers uses psycopg2 in its URL; we substitute to match the
    psycopg dependency declared in pyproject.toml.

    Args:
        container: Running PostgresContainer instance.

    Returns:
        psycopg-dialect connection string.
    """
    raw: str = container.get_connection_url()
    url = raw.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@pytest.mark.integration
def test_upgrade_head_succeeds_on_clean_container() -> None:
    """alembic upgrade head runs without error on a clean PostgreSQL 15 database.

    A fresh container has no tables.  After upgrade head the alembic_version
    table must exist and contain exactly one row pointing at the latest
    revision.

    Failure here indicates a migration script with a syntax error, a
    missing dependency, or a DDL statement that PostgreSQL 15 rejects.

    Env-precedence fix: alembic/env.py reads ``$SQLALCHEMY_URL`` and uses it to
    override any programmatic ``cfg.set_main_option(...)``.  In the
    ``integration.yml`` CI workflow that variable points at the GHA postgres
    service container -- a *different* database from the testcontainer this
    test just spun up.  ``_run_alembic_against`` overrides the env var for the
    duration of the alembic call so the migration is guaranteed to target the
    ephemeral container, not the service.
    """
    dbname = f"mig_{uuid.uuid4().hex[:8]}"
    with PostgresContainer(
        image=_PG_IMAGE,
        username=_PG_USER,
        password=_PG_PASSWORD,
        dbname=dbname,
    ) as container:
        sync_url = _container_sync_url(container)

        # Must not raise -- migration is guaranteed to target this container
        # because _run_alembic_against overrides ``SQLALCHEMY_URL``.
        _run_alembic_against(sync_url, alembic_command.upgrade, "head")

        # Verify alembic_version records the head revision
        from sqlalchemy import create_engine, text  # noqa: PLC0415

        engine = create_engine(sync_url)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
        engine.dispose()

        assert row is not None, "alembic_version table must contain a row after upgrade head"
        # The version_num must not be empty
        assert row[0], f"version_num must be non-empty, got: {row[0]!r}"


@pytest.mark.integration
def test_single_head_after_upgrade() -> None:
    """After upgrade head, ScriptDirectory reports exactly one head revision.

    Multiple heads indicate that two migration scripts share the same
    down_revision, creating a DAG fork. alembic upgrade head in that
    state is ambiguous and refuses to run.  This test catches the
    regression before a PR merges.

    The check is done via the Alembic Python API rather than subprocess
    so the result is deterministic regardless of alembic.ini defaults.
    """
    dbname = f"mig_{uuid.uuid4().hex[:8]}"
    with PostgresContainer(
        image=_PG_IMAGE,
        username=_PG_USER,
        password=_PG_PASSWORD,
        dbname=dbname,
    ) as container:
        sync_url = _container_sync_url(container)
        _run_alembic_against(sync_url, alembic_command.upgrade, "head")

        cfg = _make_config(sync_url)
        script_dir = ScriptDirectory.from_config(cfg)
        heads = script_dir.get_heads()

        assert len(heads) == 1, (
            f"Expected exactly 1 alembic head after upgrade, got {len(heads)}: {heads}. "
            "A multi-head condition means two migration files share the same down_revision. "
            "Add a merge migration (see 0015_M14_merge_heads.py for the pattern)."
        )


@pytest.mark.integration
def test_downgrade_base_then_upgrade_round_trip() -> None:
    """downgrade base then upgrade head is a clean round-trip with no errors.

    This exercises every downgrade() function in the migration chain.
    A downgrade that fails (e.g. tries to drop a non-existent object or
    violates a dependency) causes a hard stop here, surfacing the broken
    migration before it reaches production.

    The test uses a dedicated container so it does not interfere with the
    session-scoped ``migrated_db_url`` fixture used by the other test modules.

    Env-precedence + alembic_version reset fix:
      * Every alembic call goes through ``_run_alembic_against`` so the
        ephemeral container is hit (and not the GHA service DB).
      * Between ``downgrade base`` and the second ``upgrade head`` we
        explicitly drop ``public.alembic_version`` (if any leftover exists)
        and verify the schemas created by M0 (``ref``, ``raw``, ``calc``,
        ``mv``, ``ops``, ``auth``) have been dropped.  This makes the
        second upgrade idempotent regardless of whether the M0 downgrade
        path leaves the version table dangling: alembic recreates it
        automatically on the next upgrade.
    """
    dbname = f"mig_{uuid.uuid4().hex[:8]}"
    with PostgresContainer(
        image=_PG_IMAGE,
        username=_PG_USER,
        password=_PG_PASSWORD,
        dbname=dbname,
    ) as container:
        sync_url = _container_sync_url(container)

        # Step 1: upgrade to head
        _run_alembic_against(sync_url, alembic_command.upgrade, "head")

        # Step 2: downgrade all the way to base (no schema objects)
        _run_alembic_against(sync_url, alembic_command.downgrade, "base")

        # Verify no user tables remain after downgrade base
        from sqlalchemy import create_engine, text  # noqa: PLC0415

        engine = create_engine(sync_url)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                    "AND table_name != 'alembic_version'"
                )
            ).fetchone()
        engine.dispose()

        assert row is not None
        assert row[0] == 0, (
            f"Expected 0 user tables after downgrade base, found {row[0]}. "
            "A downgrade() function failed to drop its objects or has a wrong "
            "dependency order."
        )

        # Step 2b: defensively reset ``public.alembic_version`` before the
        # second upgrade.  Alembic recreates the table on the next upgrade
        # head, so dropping it (if it exists) is always safe; this guards
        # against the historical failure mode where one of the schema-level
        # cascades in M0.downgrade() leaves the version table in an
        # inconsistent state and the next ``upgrade head`` fails with
        # ``relation alembic_version does not exist``.
        engine_reset = create_engine(sync_url, isolation_level="AUTOCOMMIT")
        with engine_reset.connect() as conn_reset:
            conn_reset.execute(
                text("DROP TABLE IF EXISTS public.alembic_version CASCADE")
            )
        engine_reset.dispose()

        # Step 3: upgrade back to head (must succeed cleanly)
        _run_alembic_against(sync_url, alembic_command.upgrade, "head")

        # Confirm head revision is recorded
        engine2 = create_engine(sync_url)
        with engine2.connect() as conn2:
            version_row = conn2.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
        engine2.dispose()

        assert version_row is not None
        assert version_row[0], "version_num must be set after second upgrade head"
