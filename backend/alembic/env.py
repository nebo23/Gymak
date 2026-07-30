from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing app.models registers every table on Base.metadata (app.models.__init__).
import app.models  # noqa: F401,E402
from alembic import context
from app.config import settings
from app.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = settings.DATABASE_URL
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online_async())
