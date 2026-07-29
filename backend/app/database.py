from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for every model in app/models (spec section 4)."""


engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Second, independent barrier for set_rls_user's transaction-local app.user_id (first
    # barrier: is_local=true in set_config itself). ROLLBACK on checkin discards any
    # leftover transaction-scoped session state before a pooled connection can be handed
    # to a different request. Explicit because this is a security invariant, not merely
    # SQLAlchemy's current default -- do not remove or weaken without re-reading
    # set_rls_user's docstring below.
    pool_reset_on_return="rollback",
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def set_rls_user(session: AsyncSession, user_id: str | None) -> None:
    """Bind app.user_id for the RLS policies in spec 4.7 -- scoped to the CURRENT
    transaction ONLY, never the session or the underlying pooled connection.

    Invariant: this value must never outlive its transaction. It is set with
    set_config(..., is_local=true), the equivalent of SET LOCAL, so Postgres itself
    discards it at COMMIT or ROLLBACK. Call this once, as the first statement of the
    transaction that will run the user-scoped queries it protects; do not cache or
    reuse it across a commit.

    Raises RuntimeError if the session's connection is running under AUTOCOMMIT
    isolation. Verified empirically (not assumed): under AUTOCOMMIT, Postgres discards
    an is_local=true setting before the very next statement on the SAME connection --
    confirmed with a throwaway container, not just reasoned about -- so silently
    proceeding would mean the RLS scoping never actually applies to the query it was
    meant to protect. NOTE: AsyncSession.in_transaction() cannot detect this; it was
    tried and empirically shown to report True even under AUTOCOMMIT, because it
    reflects SQLAlchemy's own bookkeeping of whether autobegin has fired, not the
    DBAPI driver's real per-statement commit behaviour. Checking the connection's
    execution_options for an explicit isolation_level is the only reliable signal
    found for this specific misuse.

    As a second, independent barrier beyond this transaction scoping, the engine
    above is constructed with pool_reset_on_return="rollback", so even a caller that
    bypasses ORM-level close still cannot hand a tainted connection to the next
    request.
    """
    connection = await session.connection()
    sync_connection = connection.sync_connection
    assert sync_connection is not None  # always bound once session.connection() has returned
    isolation_level = sync_connection.get_execution_options().get("isolation_level")
    if isolation_level == "AUTOCOMMIT":
        raise RuntimeError(
            "set_rls_user called on a connection running under AUTOCOMMIT isolation: "
            "set_config(..., is_local=true) would be discarded before the next "
            "statement runs, so app.user_id would silently fail to scope anything. "
            "Use a normal transactional session instead."
        )
    await session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": user_id or ""}
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def database_is_reachable() -> bool:
    async with async_session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        return bool(result.scalar_one() == 1)
