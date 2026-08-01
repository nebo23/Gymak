"""§5.2 (register) and §5.3 (login), §12 T-04.

Every failure cause gets its own test, not just the happy path (per the rule this task
was given: "a rate-limit test that never sees a 429 is decoration"). The rate-limit
tests exhaust real limits rather than mocking the limiter, and the limiter is a
process-global singleton (app/core/rate_limit.py), so it is reset before and after every
test in this module -- otherwise an earlier test's register/login calls would silently
consume another test's budget, from the same test-client IP.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import hash_opaque_token
from app.database import set_rls_user
from app.models.audit import AuditLog
from app.models.refresh_token import RefreshToken
from app.models.user import User

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_LOGIN = "/api/v1/auth/login"
_PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _register(
    client: AsyncClient, *, email: str | None = None, password: str = _PASSWORD, **extra: str
):
    body = {"email": email or _unique_email(), "password": password, **extra}
    return await client.post(_REGISTER, json=body)


async def _login(client: AsyncClient, *, email: str, password: str):
    return await client.post(_LOGIN, json={"email": email, "password": password})


async def _load_user(db_session: AsyncSession, user_id: str) -> User:
    result = await db_session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    return result.scalar_one()


# --- register: happy path ---------------------------------------------------------------


async def test_register_returns_the_exact_201_shape(client: AsyncClient) -> None:
    email = _unique_email()
    response = await _register(client, email=email, language="en")

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["refresh_expires_in"] == 5_184_000
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert isinstance(body["refresh_token"], str) and body["refresh_token"]
    assert body["user"]["email"] == email
    assert body["user"]["onboarding_completed"] is False
    assert uuid.UUID(body["user"]["id"])
    assert "password_hash" not in response.text


async def test_register_persists_the_user_hashes_the_password_and_writes_the_audit_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email()
    response = await _register(client, email=email)
    user_id = response.json()["user"]["id"]

    user = await _load_user(db_session, user_id)
    assert user.email == email
    assert user.password_hash is not None
    assert user.password_hash.startswith("$argon2id$")
    assert user.password_hash != _PASSWORD
    assert user.is_active is True
    assert user.token_version == 0

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.registered", AuditLog.actor_user_id == user.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].entity == "user"
    assert audit_rows[0].entity_id == user.id


async def test_register_issues_a_refresh_token_stored_hashed_only_with_a_fresh_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await _register(client)
    body = response.json()
    user_id = uuid.UUID(body["user"]["id"])
    raw_refresh_token = body["refresh_token"]

    # refresh_tokens carries the §4.7 RLS owner policy; this session is a fresh one with
    # app.user_id unset, so it must bind it before a SELECT can see anything at all --
    # the same reasoning tests/security/test_rls.py exercises directly.
    await set_rls_user(db_session, str(user_id))
    rows = (
        (await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    token_row = rows[0]

    assert token_row.token_hash == hash_opaque_token(raw_refresh_token)
    assert token_row.token_hash != raw_refresh_token
    assert token_row.parent_id is None
    assert token_row.consumed_at is None
    assert token_row.revoked_at is None
    assert isinstance(token_row.family_id, uuid.UUID)


async def test_register_lowercases_and_trims_the_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    raw_email = f"  MixedCase-{uuid.uuid4().hex[:8]}@EXAMPLE.com  "
    normalised = raw_email.strip().lower()

    response = await _register(client, email=raw_email)
    assert response.status_code == 201
    assert response.json()["user"]["email"] == normalised

    login_response = await _login(client, email=normalised, password=_PASSWORD)
    assert login_response.status_code == 200


# --- register: failure causes -----------------------------------------------------------


async def test_register_duplicate_email_is_rejected_case_insensitively(
    client: AsyncClient,
) -> None:
    email = _unique_email()
    first = await _register(client, email=email)
    assert first.status_code == 201

    second = await _register(client, email=f"  {email.upper()}  ")
    assert second.status_code == 409
    assert second.json()["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_register_rejects_a_malformed_email(client: AsyncClient) -> None:
    response = await _register(client, email="not-an-email")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert {"field": "email", "code": "INVALID"} in body["errors"]


async def test_register_rejects_a_password_that_is_too_short(client: AsyncClient) -> None:
    response = await _register(client, password="short1")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert {"field": "password", "code": "TOO_SHORT"} in body["errors"]


async def test_register_rejects_a_common_password(client: AsyncClient) -> None:
    response = await _register(client, password="qwerty123")
    assert response.status_code == 422
    body = response.json()
    assert {"field": "password", "code": "TOO_COMMON"} in body["errors"]


async def test_register_rejects_a_password_matching_the_email_local_part(
    client: AsyncClient,
) -> None:
    response = await _register(client, email="abcdefgh@example.com", password="abcdefgh")
    assert response.status_code == 422
    body = response.json()
    assert {"field": "password", "code": "TOO_COMMON"} in body["errors"]


async def test_register_rejects_an_unsupported_language(client: AsyncClient) -> None:
    response = await _register(client, language="fr")
    assert response.status_code == 422
    body = response.json()
    assert {"field": "language", "code": "NOT_ALLOWED"} in body["errors"]


async def test_register_is_rate_limited_at_five_per_hour_per_ip(client: AsyncClient) -> None:
    for _ in range(5):
        response = await _register(client)
        assert response.status_code == 201

    refused = await _register(client)
    assert refused.status_code == 429
    body = refused.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers
    retry_after = int(refused.headers["Retry-After"])
    assert 1 <= retry_after <= 3600


# --- login: happy path -------------------------------------------------------------------


async def test_login_returns_the_exact_200_shape_and_updates_last_login(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email()
    register_response = await _register(client, email=email)
    user_id = register_response.json()["user"]["id"]

    response = await _login(client, email=email, password=_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email
    assert body["user"]["onboarding_completed"] is False
    assert "password_hash" not in response.text

    user = await _load_user(db_session, user_id)
    assert user.last_login_at is not None


async def test_login_writes_the_succeeded_audit_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email()
    register_response = await _register(client, email=email)
    user_id = uuid.UUID(register_response.json()["user"]["id"])

    await _login(client, email=email, password=_PASSWORD)

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.login_succeeded", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_login_issues_a_fresh_refresh_token_family_distinct_from_registration(
    client: AsyncClient,
) -> None:
    email = _unique_email()
    register_response = await _register(client, email=email)
    register_token = register_response.json()["refresh_token"]

    login_response = await _login(client, email=email, password=_PASSWORD)
    login_token = login_response.json()["refresh_token"]

    assert login_token != register_token


# --- login: failure causes, all one generic code -----------------------------------------


async def test_login_unknown_email_is_generic_invalid_credentials(client: AsyncClient) -> None:
    response = await _login(client, email=_unique_email("ghost"), password=_PASSWORD)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_login_wrong_password_is_generic_invalid_credentials(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email()
    register_response = await _register(client, email=email)
    user_id = uuid.UUID(register_response.json()["user"]["id"])

    response = await _login(client, email=email, password="wrong password entirely")
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.login_failed", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].event_metadata == {"reason": "invalid_credentials"}


async def test_login_unknown_email_audits_with_a_null_actor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email("ghost")
    await _login(client, email=email, password=_PASSWORD)

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.login_failed", AuditLog.actor_user_id.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) >= 1


async def test_login_soft_deleted_account_is_indistinguishable_from_unknown_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email()
    register_response = await _register(client, email=email)
    user_id = uuid.UUID(register_response.json()["user"]["id"])

    user = await _load_user(db_session, str(user_id))
    from datetime import UTC, datetime

    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    deleted_response = await _login(client, email=email, password=_PASSWORD)
    unknown_response = await _login(client, email=_unique_email("ghost"), password=_PASSWORD)

    assert deleted_response.status_code == 401
    assert deleted_response.json()["code"] == "INVALID_CREDENTIALS"
    assert deleted_response.json()["code"] == unknown_response.json()["code"]
    assert deleted_response.json()["title"] == unknown_response.json()["title"]


async def test_login_social_only_account_with_no_password_is_rejected_not_crashed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email("social")
    user = User(email=email, password_hash=None, email_verified=True)
    db_session.add(user)
    await db_session.commit()

    response = await _login(client, email=email, password="whatever-they-typed")
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_login_disabled_account_returns_account_disabled_regardless_of_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = _unique_email()
    register_response = await _register(client, email=email)
    user_id = uuid.UUID(register_response.json()["user"]["id"])

    user = await _load_user(db_session, str(user_id))
    user.is_active = False
    await db_session.commit()

    correct_password_response = await _login(client, email=email, password=_PASSWORD)
    assert correct_password_response.status_code == 403
    assert correct_password_response.json()["code"] == "ACCOUNT_DISABLED"

    wrong_password_response = await _login(client, email=email, password="not the password")
    assert wrong_password_response.status_code == 403
    assert wrong_password_response.json()["code"] == "ACCOUNT_DISABLED"

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.login_failed", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(row.event_metadata == {"reason": "account_disabled"} for row in rows)


async def test_login_is_rate_limited_at_ten_per_fifteen_minutes(client: AsyncClient) -> None:
    email = _unique_email()
    await _register(client, email=email)

    for _ in range(10):
        response = await _login(client, email=email, password="wrong password")
        assert response.status_code == 401

    refused = await _login(client, email=email, password="wrong password")
    assert refused.status_code == 429
    body = refused.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers
    retry_after = int(refused.headers["Retry-After"])
    assert 1 <= retry_after <= 900
