"""spec T-02 done-when: 'a test proves each CHECK constraint rejects an out-of-range
value (height 99, age 12, unknown goal)' -- plus the other constraint-bearing decisions
in section 4 worth verifying against a real database, not just asserted from the DDL."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.database import set_rls_user
from app.models import PasswordResetCode, Profile, RefreshToken, User, UserIdentity


def _new_email() -> str:
    return f"{uuid.uuid4()}@example.com"


def _valid_profile_kwargs(user_id: uuid.UUID) -> dict[str, object]:
    return {
        "user_id": user_id,
        "name": "Nabil",
        "gender": "male",
        "birth_date": date(2000, 1, 1),
        "height_cm": 178,
        "goal": "gain",
        "experience_level": "beginner",
    }


async def _insert_user(
    session: AsyncSession,
    *,
    password_hash: str | None = "argon2-placeholder-hash",
    email_verified: bool = False,
) -> User:
    user = User(
        id=new_id(), email=_new_email(), password_hash=password_hash, email_verified=email_verified
    )
    session.add(user)
    await session.flush()
    # profiles/refresh_tokens are FORCE ROW LEVEL SECURITY (migration): even the owner
    # role must satisfy the policy's WITH CHECK to insert into them, matching the real
    # app -- onboarding's POST /profile is authenticated, so app.user_id is already set
    # to the acting user before any such row is created. Harmless for tests that only
    # touch users/user_identities, which carry no RLS at all.
    await set_rls_user(session, str(user.id))
    return user


# --- the three boundary cases named explicitly in T-02's "Done when" -----------------


async def test_height_below_minimum_is_rejected(db_session: AsyncSession) -> None:
    user = await _insert_user(db_session)
    db_session.add(Profile(**{**_valid_profile_kwargs(user.id), "height_cm": 99}))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_age_12_is_rejected(db_session: AsyncSession) -> None:
    user = await _insert_user(db_session)
    today = date.today()
    twelve_years_ago = today.replace(year=today.year - 12)
    db_session.add(Profile(**{**_valid_profile_kwargs(user.id), "birth_date": twelve_years_ago}))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_unknown_goal_is_rejected(db_session: AsyncSession) -> None:
    user = await _insert_user(db_session)
    db_session.add(Profile(**{**_valid_profile_kwargs(user.id), "goal": "bulk"}))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# --- other constraint surface worth a real assertion, not just an eyeballed DDL -------


async def test_email_uniqueness_is_case_insensitive_for_live_rows(db_session: AsyncSession) -> None:
    email = f"{uuid.uuid4()}@Example.com"
    await _insert_user(db_session, email_verified=True)  # unrelated row, proves no false positive
    db_session.add(User(id=new_id(), email=email, password_hash="hash", email_verified=False))
    await db_session.flush()
    db_session.add(
        User(id=new_id(), email=email.lower(), password_hash="hash", email_verified=False)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_soft_deleted_email_can_be_reused(db_session: AsyncSession) -> None:
    """The partial index (WHERE deleted_at IS NULL) is the point of not using a blanket
    UNIQUE on email: spec 4.1 says a soft-deleted row is invisible to every query except
    the purge job, which only makes sense if its email can be claimed again."""
    email = _new_email()
    first = User(id=new_id(), email=email, password_hash="hash", email_verified=False)
    db_session.add(first)
    await db_session.flush()

    first.deleted_at = datetime.now(UTC)
    await db_session.flush()

    db_session.add(User(id=new_id(), email=email, password_hash="hash", email_verified=False))
    await db_session.flush()  # must not raise


async def test_credential_present_check_rejects_no_password_unverified_email(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        User(id=new_id(), email=_new_email(), password_hash=None, email_verified=False)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_credential_present_check_accepts_social_only_verified_account(
    db_session: AsyncSession,
) -> None:
    db_session.add(User(id=new_id(), email=_new_email(), password_hash=None, email_verified=True))
    await db_session.flush()  # must not raise


async def test_unknown_identity_provider_is_rejected(db_session: AsyncSession) -> None:
    user = await _insert_user(db_session)
    db_session.add(
        UserIdentity(
            id=new_id(),
            user_id=user.id,
            provider="twitter",
            provider_uid="x-1",
            firebase_uid="fb-1",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_apple_identity_provider_is_accepted_ahead_of_use(db_session: AsyncSession) -> None:
    """spec 4.2 note: 'apple' is allowed by the check now so the later phase needs no
    migration, even though nothing creates an apple identity in Phase 1."""
    user = await _insert_user(db_session)
    db_session.add(
        UserIdentity(
            id=new_id(), user_id=user.id, provider="apple", provider_uid="a-1", firebase_uid="fb-1"
        )
    )
    await db_session.flush()  # must not raise


async def test_deleting_user_cascades_to_every_dependent_table(db_session: AsyncSession) -> None:
    user = await _insert_user(db_session)
    db_session.add(Profile(**_valid_profile_kwargs(user.id)))
    db_session.add(
        UserIdentity(
            id=new_id(), user_id=user.id, provider="google", provider_uid="g-1", firebase_uid="fb-1"
        )
    )
    db_session.add(
        RefreshToken(
            id=new_id(),
            user_id=user.id,
            token_hash="token-hash-1",
            family_id=new_id(),
            expires_at=datetime.now(UTC) + timedelta(days=60),
        )
    )
    db_session.add(
        PasswordResetCode(
            id=new_id(),
            user_id=user.id,
            code_hash="code-hash-1",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await db_session.flush()

    await db_session.delete(user)
    await db_session.flush()

    assert await db_session.get(Profile, user.id) is None
    assert (
        await db_session.execute(select(UserIdentity).where(UserIdentity.user_id == user.id))
    ).first() is None
    assert (
        await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    ).first() is None
    assert (
        await db_session.execute(
            select(PasswordResetCode).where(PasswordResetCode.user_id == user.id)
        )
    ).first() is None
