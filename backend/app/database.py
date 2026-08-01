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


async def _fetch_connection_role_privileges(database_url: str) -> tuple[bool, bool, bool]:
    # A dedicated, disposable engine -- never the shared module-level `engine` -- so this
    # one-off probe cannot leave a pooled connection bound to whatever event loop happens
    # to be running when it is awaited. That exact pattern (a connection pooled under one
    # event loop, reused after that loop is gone) is what breaks asyncpg elsewhere in this
    # codebase; touching the shared pool here would reintroduce it for whatever event loop
    # actually serves the real app or test suite afterwards.
    probe_engine = create_async_engine(database_url)
    try:
        async with probe_engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, "
                    "has_schema_privilege(current_user, 'public', 'CREATE') AS can_create "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
            row = result.one()
            return bool(row.rolsuper), bool(row.rolbypassrls), bool(row.can_create)
    finally:
        await probe_engine.dispose()


async def assert_connection_is_not_privileged(database_url: str | None = None) -> None:
    """Spec 4.7: 'The application must connect as a NON-superuser role, asserted at
    startup, otherwise RLS is silently bypassed and this whole barrier is decorative.'
    A.5 item 1: extended to also refuse a role that can CREATE in schema public -- the
    application must never be able to connect as gymak_migrator, whether by a misconfigured
    DATABASE_URL or any other mixup, because a role that can create can also ALTER TABLE
    or DROP POLICY on its own tables, which is the exact self-revocable barrier the role
    split exists to close (see the split migration's docstring).

    Awaited from the FastAPI lifespan handler in main.py, not run at import time: this
    module is imported before any event loop exists under pytest (collection is
    synchronous) but *inside* an already-running loop under uvicorn (the app import
    string is resolved from within `Server.serve()`), so a self-contained
    `asyncio.run()` here would work under one runner and crash under the other with
    "asyncio.run() cannot be called from a running event loop". Awaiting it from a
    lifespan handler works under both, because both drive the app through a loop that
    is already running.

    `database_url` defaults to `settings.DATABASE_URL`, read at call time (not bound as
    a default at import time) so a test can pass a different URL -- e.g. a superuser
    role -- without mutating global settings.

    Superuser and BYPASSRLS are the two role attributes that silently bypass every RLS
    policy regardless of what the policy says; either one makes profiles/refresh_tokens
    RLS decorative, so either one is fatal here. CREATE on schema public is fatal for a
    different reason: it identifies a role that can perform DDL at all, which the
    application's role must never be able to do post-split.
    """
    is_superuser, bypasses_rls, can_create_in_schema = await _fetch_connection_role_privileges(
        database_url if database_url is not None else settings.DATABASE_URL
    )
    if is_superuser or bypasses_rls:
        raise RuntimeError(
            "Refusing to start: the database connection is a superuser or BYPASSRLS "
            f"role (rolsuper={is_superuser}, rolbypassrls={bypasses_rls}). Row-level "
            "security is silently bypassed for such roles, so the profiles/"
            "refresh_tokens RLS policies would never actually apply. Connect as a "
            "dedicated, unprivileged application role instead (see .env.example)."
        )
    if can_create_in_schema:
        raise RuntimeError(
            "Refusing to start: the database connection can CREATE objects in schema "
            "'public'. The application role (gymak_app) must hold DML only -- SELECT/"
            "INSERT/UPDATE/DELETE on specific tables -- and never schema-level CREATE. "
            "A connection that can create is either gymak_migrator (the Alembic-only "
            "role -- see MIGRATOR_DATABASE_URL) or a misconfigured DATABASE_URL; either "
            "way it must never serve the application, because it could ALTER TABLE ... "
            "NO FORCE or DROP POLICY on its own tables and make row-level security "
            "decorative (see .env.example)."
        )
