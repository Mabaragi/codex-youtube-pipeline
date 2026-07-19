from __future__ import annotations

import asyncio

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import codex_sdk_cli.infra.evaluation.models  # noqa: F401
from alembic import context
from codex_sdk_cli.infra.database.session import ensure_sqlite_parent
from codex_sdk_cli.infra.evaluation.base import EvaluationBase
from codex_sdk_cli.infra.evaluation.connections import EvaluationConnections
from codex_sdk_cli.settings import CliSettings

config = context.config
target_metadata = EvaluationBase.metadata


def _database_url() -> str:
    x_arguments = context.get_x_argument(as_dictionary=True)
    if x_arguments.get("database_url"):
        return x_arguments["database_url"]
    configured = (config.get_main_option("sqlalchemy.url") or "").strip()
    if configured:
        return configured
    settings = CliSettings()
    return EvaluationConnections.from_file(
        settings.evaluation_connections_file
    ).database.validated_url()


def run_migrations_offline() -> None:
    database_url = _database_url()
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    database_url = _database_url()
    ensure_sqlite_parent(database_url)
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = database_url
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        asyncio.run(run_async_migrations())
        return
    do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
