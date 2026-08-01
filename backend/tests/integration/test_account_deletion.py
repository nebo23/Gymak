"""§5.10 DELETE /account (P1-FR-012, §12 T-09c-2).

Covers: password required/verified when the account has one, ignored for a
social-only account; deleted_at set, token_version bumped, every refresh family
revoked, account.deletion_requested audited; the 202 shape; the access token dead
on the very next request; and login against the deleted account collapsing to the
same generic 401 INVALID_CREDENTIALS an unknown email gets (§4.1), not a 403 or 404.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.database import set_rls_user
from app.models.audit import AuditLog
from app.models.refresh_token import RefreshToken
from app.models.user import User
from tests.support import JSONDict, json_body

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_LOGIN = "/api/v1/auth/login"
_ME = "/api/v1/auth/me"
_ACCOUNT = "/api/v1/account"
_PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _register(client: AsyncClient, *, email: str | None = None) -> JSONDict:
    response = await client.post(
        _REGISTER, json={"email": email or _unique_email(), "password": _PASSWORD}
    )
    assert response.status_code == 201
    return json_body(response)


async def _delete_account(
    client: AsyncClient, *, access_token: str, password: str | None = None
) -> Response:
    body: dict[str, str] = {}
    if password is not None:
        body["password"] = password
    return await client.request(
        "DELETE",
        _ACCOUNT,
        json=body,
        headers={"Authorization": f"Bearer {access_token}"},
    )


async def _load_user(db_session: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db_session.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


# --- password required / verified for a password-holding account -----------------------


async def test_delete_account_rejects_a_wrong_password(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _delete_account(
        client, access_token=registered["access_token"], password="not the password"
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_delete_account_rejects_a_missing_password_when_one_is_required(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    response = await _delete_account(client, access_token=registered["access_token"])
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_delete_account_does_not_delete_on_a_failed_password_check(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])

    response = await _delete_account(
        client, access_token=registered["access_token"], password="wrong"
    )
    assert response.status_code == 401

    user = await _load_user(db_session, user_id)
    assert user.deleted_at is None


# --- happy path: password-holding account --------------------------------------------


async def test_delete_account_succeeds_with_the_correct_password(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _delete_account(
        client, access_token=registered["access_token"], password=_PASSWORD
    )
    assert response.status_code == 202
    body = response.json()
    assert body["purge_after_days"] == 30
    assert datetime.fromisoformat(body["deletion_requested_at"].replace("Z", "+00:00"))


async def test_delete_account_sets_deleted_at_bumps_token_version_revokes_refresh_and_audits(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])

    response = await _delete_account(
        client, access_token=registered["access_token"], password=_PASSWORD
    )
    assert response.status_code == 202

    user = await _load_user(db_session, user_id)
    assert user.deleted_at is not None
    assert user.token_version == 1

    await set_rls_user(db_session, str(user_id))
    tokens = (
        (await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id)))
        .scalars()
        .all()
    )
    assert tokens
    assert all(token.revoked_at is not None for token in tokens)

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "account.deletion_requested",
                    AuditLog.actor_user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].entity == "user"
    assert audit_rows[0].entity_id == user_id


# --- social-only account: password not required, and ignored if sent --------------------


async def test_delete_account_does_not_require_a_password_for_a_social_only_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email("social")
    user = User(email=email, password_hash=None, email_verified=True)
    db_session.add(user)
    await db_session.commit()
    access_token, _expires_in = create_access_token(user_id=user.id, token_version=0)

    response = await _delete_account(client, access_token=access_token)
    assert response.status_code == 202

    deleted = await _load_user(db_session, user.id)
    assert deleted.deleted_at is not None


async def test_delete_account_ignores_a_password_sent_for_a_social_only_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A social-only account has nothing to check a submitted password against --
    whatever the caller sends must be silently ignored, not rejected, mirroring §5.4's
    "extra body fields do not influence the outcome" posture.
    """
    email = _unique_email("social")
    user = User(email=email, password_hash=None, email_verified=True)
    db_session.add(user)
    await db_session.commit()
    access_token, _expires_in = create_access_token(user_id=user.id, token_version=0)

    response = await _delete_account(client, access_token=access_token, password="irrelevant")
    assert response.status_code == 202


# --- the two proofs the task calls out explicitly ----------------------------------------


async def test_access_token_is_dead_on_the_next_request_after_deletion(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]

    delete_response = await _delete_account(client, access_token=access_token, password=_PASSWORD)
    assert delete_response.status_code == 202

    me_response = await client.get(_ME, headers={"Authorization": f"Bearer {access_token}"})
    assert me_response.status_code == 401


async def test_login_against_a_deleted_account_is_generic_invalid_credentials(
    client: AsyncClient,
) -> None:
    email = _unique_email()
    registered = await _register(client, email=email)

    delete_response = await _delete_account(
        client, access_token=registered["access_token"], password=_PASSWORD
    )
    assert delete_response.status_code == 202

    login_response = await client.post(_LOGIN, json={"email": email, "password": _PASSWORD})
    unknown_response = await client.post(
        _LOGIN, json={"email": _unique_email("ghost"), "password": _PASSWORD}
    )

    assert login_response.status_code == 401
    assert login_response.json()["code"] == "INVALID_CREDENTIALS"
    assert login_response.json()["code"] == unknown_response.json()["code"]
    assert login_response.json()["title"] == unknown_response.json()["title"]


# --- no response body anywhere contains password_hash ------------------------------------


async def test_delete_account_response_never_contains_password_hash(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _delete_account(
        client, access_token=registered["access_token"], password=_PASSWORD
    )
    assert "password_hash" not in response.text


# --- auth: no token, foreign token ---------------------------------------------------


async def test_delete_account_without_a_bearer_token_is_rejected(client: AsyncClient) -> None:
    response = await client.request("DELETE", _ACCOUNT, json={})
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_MISSING"
