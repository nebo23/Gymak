"""get_current_user / require_active (§3, §7.3).

These need a real user row, so they run against the testcontainers PostgreSQL the suite
already provides. Nothing is committed: the session fixture rolls back on close.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_active
from app.core.errors import register_exception_handlers
from app.core.ids import new_id
from app.core.security import create_access_token, hash_password
from app.models.user import User


async def _make_user(
    session: AsyncSession,
    *,
    token_version: int = 0,
    is_active: bool = True,
) -> User:
    user = User(
        id=new_id(),
        email=f"dep-{uuid.uuid4().hex[:12]}@example.com",
        password_hash=hash_password("correct horse battery"),
        email_verified=False,
        token_version=token_version,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def app_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """A minimal app with two protected routes, sharing the test's session so a flushed
    (uncommitted) user is visible to the dependency."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/whoami")
    async def whoami(user: Annotated[User, Depends(get_current_user)]) -> dict[str, str]:
        return {"id": str(user.id), "email": user.email}

    @app.get("/active-only")
    async def active_only(user: Annotated[User, Depends(require_active)]) -> dict[str, str]:
        return {"id": str(user.id)}

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the header ------------------------------------------------------------------------


async def test_no_authorization_header_is_token_missing(app_client: AsyncClient) -> None:
    response = await app_client.get("/whoami")
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_MISSING"
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer    "},
        {"Authorization": ""},
        {"Authorization": "token-without-a-scheme"},
    ],
)
async def test_a_header_that_is_not_a_bearer_token_is_token_missing(
    app_client: AsyncClient, header: dict[str, str]
) -> None:
    """TOKEN_MISSING, not TOKEN_INVALID: there is nothing to verify. §7.3 keeps them apart so
    the client can tell "you never sent a token" from "your token is dead"."""
    response = await app_client.get("/whoami", headers=header)
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_MISSING"


# --- the token -------------------------------------------------------------------------


async def test_a_garbage_token_is_token_invalid(app_client: AsyncClient) -> None:
    response = await app_client.get("/whoami", headers=_bearer("not.a.jwt"))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_a_valid_token_for_an_unknown_user_is_token_invalid(
    app_client: AsyncClient,
) -> None:
    """A perfectly signed token whose subject has no row -- what an old token looks like after
    a hard delete. TOKEN_INVALID rather than 404: the token is the thing being rejected, and a
    404 would confirm which user ids exist."""
    token, _ = create_access_token(user_id=uuid.uuid4(), token_version=0)
    response = await app_client.get("/whoami", headers=_bearer(token))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_an_expired_token_is_token_expired(app_client: AsyncClient) -> None:
    from app.config import settings

    original = settings.ACCESS_TOKEN_TTL_SECONDS
    try:
        settings.ACCESS_TOKEN_TTL_SECONDS = -10
        token, _ = create_access_token(user_id=uuid.uuid4(), token_version=0)
    finally:
        settings.ACCESS_TOKEN_TTL_SECONDS = original

    response = await app_client.get("/whoami", headers=_bearer(token))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


# --- the user row ----------------------------------------------------------------------


async def test_a_live_user_with_a_current_token_is_returned(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, token_version=4)
    token, _ = create_access_token(user_id=user.id, token_version=4)

    response = await app_client.get("/whoami", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {"id": str(user.id), "email": user.email}


async def test_a_stale_token_version_is_rejected(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """P1-ADR-02: logout-all, password reset and account deletion all work by bumping
    token_version, so this is the check that makes those revocations real."""
    user = await _make_user(db_session, token_version=1)
    token, _ = create_access_token(user_id=user.id, token_version=1)
    assert (await app_client.get("/whoami", headers=_bearer(token))).status_code == 200

    user.token_version = 2
    await db_session.flush()

    response = await app_client.get("/whoami", headers=_bearer(token))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_a_soft_deleted_user_is_rejected(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """§4.1: a row with deleted_at IS NOT NULL is invisible to every query except the purge
    job. The filter is in user_repo's SQL, so the token simply finds nobody."""
    user = await _make_user(db_session)
    token, _ = create_access_token(user_id=user.id, token_version=0)
    assert (await app_client.get("/whoami", headers=_bearer(token))).status_code == 200

    await db_session.execute(
        text("UPDATE users SET deleted_at = now() WHERE id = :id"), {"id": user.id}
    )
    await db_session.flush()
    db_session.expire_all()

    response = await app_client.get("/whoami", headers=_bearer(token))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_an_inactive_user_gets_account_disabled_not_token_invalid(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """§7.3 maps is_active=false to 403 ACCOUNT_DISABLED, and §5.3 gives the reason: this is
    the one case where the user needs to know why, so it must not be folded into the generic
    token rejection."""
    user = await _make_user(db_session, is_active=False)
    token, _ = create_access_token(user_id=user.id, token_version=0)

    response = await app_client.get("/whoami", headers=_bearer(token))
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_DISABLED"


# --- RLS binding -----------------------------------------------------------------------


async def test_authenticating_binds_app_user_id_for_rls(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """§4.7's second barrier. The policies compare user_id to current_setting('app.user_id'),
    which is worth nothing unless something sets it -- this is where that happens."""
    user = await _make_user(db_session)
    token, _ = create_access_token(user_id=user.id, token_version=0)

    assert (await app_client.get("/whoami", headers=_bearer(token))).status_code == 200

    bound = await db_session.execute(text("SELECT current_setting('app.user_id', true)"))
    assert bound.scalar_one() == str(user.id)


async def test_a_rejected_request_does_not_bind_app_user_id(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Fail-closed: RLS must not be bound to anyone on a request that never authenticated."""
    await app_client.get("/whoami", headers=_bearer("not.a.jwt"))
    bound = await db_session.execute(text("SELECT current_setting('app.user_id', true)"))
    assert bound.scalar_one() in (None, "")


# --- require_active --------------------------------------------------------------------


async def test_require_active_admits_a_live_enabled_user(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    token, _ = create_access_token(user_id=user.id, token_version=0)
    response = await app_client.get("/active-only", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {"id": str(user.id)}


async def test_require_active_rejects_a_disabled_user(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, is_active=False)
    token, _ = create_access_token(user_id=user.id, token_version=0)
    response = await app_client.get("/active-only", headers=_bearer(token))
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_DISABLED"


async def test_get_current_user_alone_already_rejects_a_disabled_user(
    app_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The reason require_active is not where the check lives: a dependency that is only safe
    when composed with a second one will eventually be used without it."""
    user = await _make_user(db_session, is_active=False)
    token, _ = create_access_token(user_id=user.id, token_version=0)
    assert (await app_client.get("/whoami", headers=_bearer(token))).status_code == 403
