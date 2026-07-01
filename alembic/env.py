# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Alembic env. Loads DB URL from surge_quality.settings, binds metadata
from surge_quality.db.Base. All migrations live under surge_quality schema."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from surge_quality.db import Base
from surge_quality.settings import get_settings

# Importing models registers them on Base.metadata.
from surge_quality import models  # noqa: F401

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ARG001
    """Restrict autogenerate to the surge_quality schema."""
    if type_ == "table" and obj.schema != _settings.db_schema:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=_settings.db_schema,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _try_create_schema(connectable) -> None:
    """Best-effort CREATE SCHEMA. The production surge_quality role does NOT
    own the database, so this errors with InsufficientPrivilege — that is
    fine, because the schema is provisioned out-of-band before the role is
    granted login. Done in its own short-lived connection so a failure here
    cannot poison the main migration transaction."""
    try:
        with connectable.connect() as c:
            c.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{_settings.db_schema}"')
            c.commit()
    except Exception:
        # Either we lack privilege (production role) or already exists.
        # Both are non-blocking — the schema must exist by the time we run.
        pass


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    _try_create_schema(connectable)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=_settings.db_schema,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
