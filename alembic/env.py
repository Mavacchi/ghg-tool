"""Alembic environment configuration for GHG Accounting Tool.

Supports both offline SQL generation and online migration against a live
PostgreSQL 15 instance.  The ``sqlalchemy.url`` may be overridden via the
``SQLALCHEMY_URL`` environment variable for CI / production use.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Alembic Config object
# ---------------------------------------------------------------------------
config = context.config

# Allow environment-variable override (safer than baking credentials into ini)
db_url = os.environ.get("SQLALCHEMY_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Metadata — import ORM Base once models are wired in wave 2.
# For wave 1, migrations are generated via op.execute() only (raw SQL DDL).
# ---------------------------------------------------------------------------
target_metadata = None  # wave 2: from ghg_tool.infrastructure.db.base import Base; target_metadata = Base.metadata  # noqa: E501


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout).

    Useful for reviewing DDL before applying to a production database, and for
    CI ``alembic upgrade head --sql`` validation.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
