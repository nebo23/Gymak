"""§5.5 (refresh rotation), §5's /auth/logout and /auth/logout-all, §12 T-05.

The reuse test is the one that actually matters here, per the rule this task was
given: rotating A into B and then presenting A again must leave B dead too, not merely
reject the second presentation of A -- an implementation that never revokes the family
would still pass a test that only checks the second call's status code.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.database import set_rls_user
from app.models.audit import AuditLog
from app.models.refresh_token import RefreshToken

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_REFRESH = "/api/v1/auth/refresh"
_LOGOUT = "/api/v1/auth/logout"
_LOGOUT_ALL = "/api/v1/auth/logout-all"
_PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _register(client: AsyncClient, *, email: str | None = None) -> dict:
    response = await client.post(
        _REGISTER, json={"email": email or _unique_email(), "password": _PASSWORD}
    )
    assert response.status_code == 201
    return response.json()


async def _refresh(client: AsyncClient, refresh_token: str):
    return await client.post(_REFRESH, json={"refresh_token": refresh_token})


async def _logout(client: AsyncClient, *, access_token: str, refresh_token: str):
    return await client.post(
        _LOGOUT,
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {access_token}"},
    )


async def _logout_all(client: AsyncClient, *, access_token: str):
    return await client.post(_LOGOUT_ALL, headers={"Authorization": f"Bearer {access_token}"})


async def _get_token_row(db_session: AsyncSession, token_hash: str) -> RefreshToken:
    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    return result.scalar_one()


async def _hash_of(raw_refresh_token: str) -> str:
    from app.core.security import hash_opaque_token

    return hash_opaque_token(raw_refresh_token)


async def _force_expire(
    db_session: AsyncSession, user_id: uuid.UUID, raw_refresh_token: str
) -> None:
    await set_rls_user(db_session, str(user_id))
    row = await _get_token_row(db_session, await _hash_of(raw_refresh_token))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()


async def _force_revoke(
    db_session: AsyncSession, user_id: uuid.UUID, raw_refresh_token: str
) -> None:
    await set_rls_user(db_session, str(user_id))
    row = await _get_token_row(db_session, await _hash_of(raw_refresh_token))
    row.revoked_at = datetime.now(UTC)
    await db_session.commit()


# --- happy path ---------------------------------------------------------------------


async def test_refresh_rotates_the_token_and_audits_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])
    token_a = registered["refresh_token"]

    response = await _refresh(client, token_a)
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] != registered["access_token"]
    assert body["refresh_token"] != token_a
    assert body["token_type"] == "bearer"

    await set_rls_user(db_session, str(user_id))
    row_a = await _get_token_row(db_session, await _hash_of(token_a))
    row_b = await _get_token_row(db_session, await _hash_of(body["refresh_token"]))
    assert row_a.consumed_at is not None
    assert row_a.revoked_at is None
    assert row_b.parent_id == row_a.id
    assert row_b.family_id == row_a.family_id
    assert row_b.consumed_at is None

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "token.refreshed", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1


# --- reuse: the test that matters -----------------------------------------------------


async def test_refresh_reuse_revokes_the_whole_family_not_just_the_presented_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])
    token_a = registered["refresh_token"]

    rotated = await _refresh(client, token_a)
    assert rotated.status_code == 200
    token_b = rotated.json()["refresh_token"]

    reuse_response = await _refresh(client, token_a)
    assert reuse_response.status_code == 401
    assert reuse_response.json()["code"] == "TOKEN_REUSED"

    # The assertion that actually matters: B -- the LEGITIMATE successor that was never
    # itself reused -- must be dead too. A test that stops at the line above would still
    # pass against an implementation that only rejects the reused token and never
    # touches the rest of the family.
    b_after_reuse = await _refresh(client, token_b)
    assert b_after_reuse.status_code == 401
    assert b_after_reuse.json()["code"] == "TOKEN_INVALID"

    await set_rls_user(db_session, str(user_id))
    family_rows = (
        (await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(family_rows) == 2
    assert all(row.revoked_at is not None for row in family_rows)

    reuse_audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "token.reuse_detected", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(reuse_audit) == 1

    family_revoked_audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "token.family_revoked", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(family_revoked_audit) == 1
    assert family_revoked_audit[0].event_metadata == {"reason": "reuse_detected"}


# --- refresh: every other failure cause -----------------------------------------------


async def test_refresh_with_an_expired_token_returns_token_expired(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])
    token_a = registered["refresh_token"]

    await _force_expire(db_session, user_id, token_a)

    response = await _refresh(client, token_a)
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


async def test_refresh_with_a_revoked_token_returns_token_invalid(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])
    token_a = registered["refresh_token"]

    await _force_revoke(db_session, user_id, token_a)

    response = await _refresh(client, token_a)
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_refresh_with_an_unknown_token_returns_token_invalid(client: AsyncClient) -> None:
    response = await _refresh(client, "this-was-never-issued-by-anything")
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_refresh_with_a_soft_deleted_users_token_returns_token_invalid(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.user import User

    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])
    token_a = registered["refresh_token"]

    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    response = await _refresh(client, token_a)
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_INVALID"


async def test_refresh_is_rate_limited_at_sixty_per_hour_per_user(client: AsyncClient) -> None:
    registered = await _register(client)
    current_token = registered["refresh_token"]

    for _ in range(60):
        response = await _refresh(client, current_token)
        assert response.status_code == 200
        current_token = response.json()["refresh_token"]

    refused = await _refresh(client, current_token)
    assert refused.status_code == 429
    body = refused.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers
    retry_after = int(refused.headers["Retry-After"])
    assert 1 <= retry_after <= 3600


# --- logout / logout-all ---------------------------------------------------------------


async def test_logout_revokes_the_current_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])
    access_token = registered["access_token"]
    refresh_token = registered["refresh_token"]

    response = await _logout(client, access_token=access_token, refresh_token=refresh_token)
    assert response.status_code == 204

    still_usable = await _refresh(client, refresh_token)
    assert still_usable.status_code == 401
    assert still_usable.json()["code"] == "TOKEN_INVALID"

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "token.family_revoked", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].event_metadata == {"reason": "logout"}


async def test_logout_with_an_unknown_or_foreign_refresh_token_is_rejected(
    client: AsyncClient,
) -> None:
    registered_a = await _register(client)
    registered_b = await _register(client)

    # b's own access token, but a's refresh token in the body -- must not revoke a's
    # family, and must be indistinguishable from a token that was never issued at all.
    cross_user_response = await _logout(
        client,
        access_token=registered_b["access_token"],
        refresh_token=registered_a["refresh_token"],
    )
    assert cross_user_response.status_code == 401
    assert cross_user_response.json()["code"] == "TOKEN_INVALID"

    # a's own family must still be live: refreshing it still works.
    still_works = await _refresh(client, registered_a["refresh_token"])
    assert still_works.status_code == 200

    unknown_response = await _logout(
        client,
        access_token=registered_b["access_token"],
        refresh_token="this-was-never-issued-by-anything",
    )
    assert unknown_response.status_code == 401
    assert unknown_response.json()["code"] == "TOKEN_INVALID"


async def test_logout_all_revokes_every_family_and_bumps_token_version(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.user import User

    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])
    old_access_token = registered["access_token"]
    refresh_token = registered["refresh_token"]

    response = await _logout_all(client, access_token=old_access_token)
    assert response.status_code == 204

    result = await db_session.execute(select(User).where(User.id == user_id))
    assert result.scalar_one().token_version == 1

    dead_refresh = await _refresh(client, refresh_token)
    assert dead_refresh.status_code == 401
    assert dead_refresh.json()["code"] == "TOKEN_INVALID"

    # §P1-ADR-02: bumping token_version invalidates every access token issued before the
    # bump, immediately -- not merely at its own 15-minute expiry. Proven by presenting
    # the pre-logout-all access token to another bearer-authenticated route and getting
    # rejected on `tv` mismatch, per get_current_user's ordering.
    stale_access_token_rejected = await _logout_all(client, access_token=old_access_token)
    assert stale_access_token_rejected.status_code == 401
    assert stale_access_token_rejected.json()["code"] == "TOKEN_INVALID"
