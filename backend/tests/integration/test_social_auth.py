"""§5.4 POST /auth/social/{provider} (P1-FR-003, §12 T-06). Google only in Phase 1 --
decision 13.1.2 (A-15).

Firebase is never called: every test mocks app.integrations.firebase.verify_id_token
directly and asserts on what social_service does with the claims it returns, per the
task's own rule. The unverified-email test is written as a control (it asserts a
takeover is prevented and the victim's row is untouched), not as a coverage test.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.integrations import firebase
from app.models.audit import AuditLog
from app.models.identity import UserIdentity
from app.models.user import User
from app.repositories import identity_repo

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_SOCIAL_GOOGLE = "/api/v1/auth/social/google"
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


def _claims(
    *,
    provider_uid: str,
    email: str | None,
    email_verified: bool,
    sign_in_provider: str = "google.com",
    firebase_uid: str | None = None,
) -> dict[str, object]:
    """A Firebase-decoded-token shape, hand-built so tests control exactly what
    _extract_claims (app/services/social_service.py) has to work with -- real shape:
    top-level `uid`, `email`, `email_verified`, and a nested `firebase.sign_in_provider`
    / `firebase.identities` block.
    """
    identities: dict[str, list[str]] = {sign_in_provider: [provider_uid]}
    claims: dict[str, object] = {
        "uid": firebase_uid or f"firebase-{provider_uid}",
        "email_verified": email_verified,
        "firebase": {"sign_in_provider": sign_in_provider, "identities": identities},
    }
    if email:
        claims["email"] = email
        identities["email"] = [email]
    return claims


async def _count_users_with_email(db_session: AsyncSession, email: str) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(User).where(User.email == email)
    )
    return result.scalar_one()


# --- the seven required cases ----------------------------------------------------------


async def test_new_user_created_via_google_sign_in(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email()
    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(provider_uid="new-uid-1", email=email, email_verified=True),
    )

    response = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_new_user"] is True
    assert body["user"]["email"] == email
    assert body["access_token"] and body["refresh_token"]

    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.password_hash is None
    assert user.email_verified is True

    identity = (
        await db_session.execute(select(UserIdentity).where(UserIdentity.user_id == user.id))
    ).scalar_one()
    assert identity.provider == "google"
    assert identity.provider_uid == "new-uid-1"


async def test_returning_user_signs_in_via_existing_identity(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email()
    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(provider_uid="return-uid-1", email=email, email_verified=True),
    )

    first = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t1"})
    assert first.status_code == 200
    assert first.json()["is_new_user"] is True
    user_id = first.json()["user"]["id"]

    second = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t2"})
    assert second.status_code == 200
    assert second.json()["is_new_user"] is False
    assert second.json()["user"]["id"] == user_id

    assert await _count_users_with_email(db_session, email) == 1


async def test_links_to_existing_user_on_verified_matching_email(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = await _register(client)
    email = registered["user"]["email"]
    existing_user_id = registered["user"]["id"]

    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(provider_uid="link-uid-1", email=email, email_verified=True),
    )

    response = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_new_user"] is False
    assert body["user"]["id"] == existing_user_id

    assert await _count_users_with_email(db_session, email) == 1

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.social_linked",
                    AuditLog.actor_user_id == uuid.UUID(existing_user_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1


async def test_unverified_email_does_not_link_to_existing_user(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control test. If this links, anyone who can register `victim_email` at
    Google without proving they own it takes over the Gymak account it matches --
    since Google's own `email_verified` is exactly the signal that distinguishes "this
    person proved ownership" from "this person merely typed an address". Asserts a
    SEPARATE account is created, and that the victim's row is provably untouched: same
    password_hash, same updated_at, no identity attached, no social_linked audit row.
    """
    registered = await _register(client)
    victim_email = registered["user"]["email"]
    victim_id = uuid.UUID(registered["user"]["id"])

    before = (await db_session.execute(select(User).where(User.id == victim_id))).scalar_one()
    before_password_hash = before.password_hash
    before_updated_at = before.updated_at

    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(
            provider_uid="attacker-uid-1", email=victim_email, email_verified=False
        ),
    )

    response = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_new_user"] is True
    assert body["user"]["id"] != str(victim_id)
    # The takeover this test exists to rule out: the attacker's session must not be
    # bound to the victim's account or its email.
    assert body["user"]["email"] != victim_email

    after = (await db_session.execute(select(User).where(User.id == victim_id))).scalar_one()
    assert after.password_hash == before_password_hash
    assert after.updated_at == before_updated_at
    assert after.email == victim_email

    linked_to_victim = (
        (await db_session.execute(select(UserIdentity).where(UserIdentity.user_id == victim_id)))
        .scalars()
        .all()
    )
    assert linked_to_victim == []

    link_audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.social_linked", AuditLog.actor_user_id == victim_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert link_audit == []


async def test_provider_claim_mismatch_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5.4 step 2: a token minted for a different Firebase sign-in provider than the
    path must not be accepted -- "Without this check, a Google token would be accepted
    at the Facebook endpoint," and the reverse is what's constructible while Facebook is
    deferred: a token asserting facebook.com presented at /auth/social/google.
    """
    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(
            provider_uid="mismatch-uid",
            email=_unique_email(),
            email_verified=True,
            sign_in_provider="facebook.com",
        ),
    )

    response = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t"})
    assert response.status_code == 401
    assert response.json()["code"] == "SOCIAL_TOKEN_INVALID"


async def test_missing_email_uses_placeholder_scheme(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(provider_uid="no-email-uid", email=None, email_verified=False),
    )

    response = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_new_user"] is True
    assert body["user"]["email"] == "google_no-email-uid@social.gymak.local"

    user = (
        await db_session.execute(select(User).where(User.id == uuid.UUID(body["user"]["id"])))
    ).scalar_one()
    assert user.email_verified is False


async def test_identity_already_linked_to_another_user_returns_409(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4.2's UNIQUE(provider, provider_uid) is the real barrier; the lookup in
    social_service.sign_in and the identity insert are not atomic, so a concurrent
    sign-in for the same identity can race between them. Simulated deterministically
    here: a real conflicting row already exists, and the initial lookup is patched to
    report "not found" (the race window) so the insert below it hits the constraint for
    real.
    """
    other = await _register(client)
    other_user_id = uuid.UUID(other["user"]["id"])

    db_session.add(
        UserIdentity(
            user_id=other_user_id,
            provider="google",
            provider_uid="raced-uid",
            firebase_uid="firebase-raced-uid",
            email_at_provider=None,
        )
    )
    await db_session.commit()

    async def _pretend_not_found(session: AsyncSession, provider: str, provider_uid: str) -> None:
        return None

    monkeypatch.setattr(identity_repo, "get_by_provider_uid", _pretend_not_found)

    attacker_email = _unique_email()
    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(
            provider_uid="raced-uid", email=attacker_email, email_verified=True
        ),
    )

    response = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t"})
    assert response.status_code == 409
    assert response.json()["code"] == "IDENTITY_ALREADY_LINKED"

    # The failed attempt must not leave an orphan user behind -- the whole thing rolls
    # back, not just the identity insert.
    assert await _count_users_with_email(db_session, attacker_email) == 0

    still_just_one_identity = (
        (
            await db_session.execute(
                select(UserIdentity).where(
                    UserIdentity.provider == "google", UserIdentity.provider_uid == "raced-uid"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(still_just_one_identity) == 1
    assert still_just_one_identity[0].user_id == other_user_id


async def test_unverified_email_with_no_collision_still_becomes_the_new_accounts_email(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The placeholder scheme exists to dodge a real collision (see the control test
    above) or to cover a provider that returned no email at all -- not to distrust every
    unverified email unconditionally. An unverified email nobody else holds still seeds
    the new account, carrying email_verified=false through untouched.
    """
    free_email = _unique_email()
    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(
            provider_uid="unverified-free-uid", email=free_email, email_verified=False
        ),
    )

    response = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_new_user"] is True
    assert body["user"]["email"] == free_email

    user = (await db_session.execute(select(User).where(User.email == free_email))).scalar_one()
    assert user.email_verified is False
    assert user.password_hash is None


async def test_identity_attached_to_a_disabled_account_is_rejected(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _unique_email()
    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(provider_uid="disabled-uid", email=email, email_verified=True),
    )

    first = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t1"})
    assert first.status_code == 200
    user_id = uuid.UUID(first.json()["user"]["id"])

    user = (await db_session.execute(select(User).where(User.id == user_id))).scalar_one()
    user.is_active = False
    await db_session.commit()

    second = await client.post(_SOCIAL_GOOGLE, json={"id_token": "t2"})
    assert second.status_code == 403
    assert second.json()["code"] == "ACCOUNT_DISABLED"


# --- "do not trust the client's claim about who it is" ----------------------------------


async def test_request_body_extra_fields_do_not_influence_the_outcome(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The body carries exactly one field, id_token. An attacker-controlled `email` and
    `provider` sent alongside a valid token must be silently ignored -- the outcome must
    be identical to a request that sent id_token alone.
    """
    real_email = _unique_email()
    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: _claims(
            provider_uid="body-ignore-uid", email=real_email, email_verified=True
        ),
    )

    response = await client.post(
        _SOCIAL_GOOGLE,
        json={"id_token": "t", "email": "attacker@evil.example", "provider": "facebook"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == real_email
    assert body["is_new_user"] is True

    attacker_planted = await _count_users_with_email(db_session, "attacker@evil.example")
    assert attacker_planted == 0


# --- other controls ----------------------------------------------------------------------


async def test_unsupported_provider_returns_400_without_calling_firebase(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(id_token: str) -> dict[str, object]:
        raise AssertionError("firebase.verify_id_token must not be called for facebook yet")

    monkeypatch.setattr(firebase, "verify_id_token", _fail)

    response = await client.post("/api/v1/auth/social/facebook", json={"id_token": "t"})
    assert response.status_code == 400
    assert response.json()["code"] == "PROVIDER_NOT_SUPPORTED"


async def test_firebase_verification_failure_returns_social_token_invalid(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(id_token: str) -> dict[str, object]:
        raise ValueError("token signature invalid")

    monkeypatch.setattr(firebase, "verify_id_token", _raise)

    response = await client.post(_SOCIAL_GOOGLE, json={"id_token": "bad"})
    assert response.status_code == 401
    assert response.json()["code"] == "SOCIAL_TOKEN_INVALID"


async def test_social_sign_in_is_rate_limited_at_twenty_per_hour_per_ip(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fresh_claims(id_token: str) -> dict[str, object]:
        return _claims(provider_uid=f"rl-{id_token}", email=_unique_email(), email_verified=True)

    monkeypatch.setattr(firebase, "verify_id_token", _fresh_claims)

    for i in range(20):
        response = await client.post(_SOCIAL_GOOGLE, json={"id_token": str(i)})
        assert response.status_code == 200

    refused = await client.post(_SOCIAL_GOOGLE, json={"id_token": "one-too-many"})
    assert refused.status_code == 429
    assert refused.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers
