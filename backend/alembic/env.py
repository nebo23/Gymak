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


def _migrator_database_url() -> str:
    """A.5 item 1: Alembic must connect as gymak_migrator, never as gymak_app -- the
    application's DATABASE_URL is a DML-only role that, post-split, cannot even run
    CREATE TABLE, let alone the rest of what a migration does. Deliberately a separate
    Settings field (app/config.py's MIGRATOR_DATABASE_URL) rather than reusing
    DATABASE_URL for both: the application itself never reads this field, so the two
    identities stay genuinely distinct settings, not one URL doing double duty.
    """
    if settings.MIGRATOR_DATABASE_URL is None:
        raise RuntimeError(
            "MIGRATOR_DATABASE_URL is not set. Alembic connects as gymak_migrator, the "
            "schema-owning role -- never as the application's gymak_app, which holds DML "
            "only from this point in the migration chain onward (see docs/PHASE-1-SPEC.md "
            "§4.7/§6.5 and Appendix A.1). Set MIGRATOR_DATABASE_URL in .env before running "
            "migrations."
        )
    return settings.MIGRATOR_DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=_migrator_database_url(),
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
    configuration["sqlalchemy.url"] = _migrator_database_url()
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
