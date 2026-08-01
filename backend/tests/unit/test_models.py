"""spec T-02 done-when: 'a test proves each CHECK constraint rejects an out-of-range
value (height 99, age 12, unknown goal)' -- plus the other constraint-bearing decisions
in section 4 worth verifying against a real database, not just asserted from the DDL."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

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


async def test_credential_present_trigger_rejects_orphan_user_at_commit(
    db_session: AsyncSession,
) -> None:
    """A.5 item 14: T-02 shipped chk_credential_present -- "password_hash IS NOT NULL
    OR email_verified = true" -- on the assumption that a password and a verified email
    were the only two ways into an account. T-06 (§5.4 step 5) added a third: a social
    sign-in with no usable email creates a user reachable only through a linked
    user_identities row. Postgres CHECK constraints cannot see across tables, so T-06
    dropped the CHECK entirely (migration 2b58d76b93fb) rather than leave it checking
    only two of the three cases, and the guarantee moved into social_service.py
    inserting both rows in one transaction -- a convention, not a barrier.

    Migration ae026cea6d8d replaces that convention with a DEFERRABLE constraint
    trigger enforcing the real three-way invariant at COMMIT. A user row with no
    password, no verified email, and no linked identity -- exactly the row the
    dropped CHECK used to reject, and exactly what a bug elsewhere in the codebase
    could otherwise insert unnoticed -- must not survive a commit.

    The trigger is DEFERRED, not immediate: `flush()` alone must not raise (the
    transaction may still be building up the matching identity row), only `commit()`
    does -- see the next test for the legitimate case this has to keep allowing.
    """
    db_session.add(User(id=new_id(), email=_new_email(), password_hash=None, email_verified=False))
    await db_session.flush()  # the trigger is deferred: no violation yet
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_credential_present_trigger_allows_placeholder_account_with_identity(
    db_session: AsyncSession,
) -> None:
    """The legitimate case §5.4 step 5 needs, and A.5 item 14's gap (a): a user with no
    password and no verified email, but a linked user_identities row inserted in the
    same transaction -- exactly what social_service.py does for a social sign-in with
    no usable email. Must commit cleanly; the trigger only fires because the identity
    row exists by the time COMMIT evaluates it.
    """
    user = User(id=new_id(), email=_new_email(), password_hash=None, email_verified=False)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserIdentity(
            id=new_id(),
            user_id=user.id,
            provider="google",
            provider_uid=str(uuid.uuid4()),
            firebase_uid=str(uuid.uuid4()),
        )
    )
    await db_session.commit()  # must not raise


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


async def test_deleting_user_cascades_to_every_dependent_table(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    """A.5 item 1: gymak_app holds no DELETE on users -- the application never hard-
    deletes an account (§4.1: deletion is `deleted_at`, an UPDATE; "a purge job (later
    phase) reads this column"). The ON DELETE CASCADE definitions in §4 are still real
    schema, worth proving, but the DELETE itself is now issued as gymak_migrator, the
    table owner -- not through db_session, which is gymak_app throughout the rest of
    this test suite. Everything else about this test -- the setup and the read-back
    assertions -- stays on db_session so the cascade is verified the same way it always
    was, via a connection that is unambiguously not the one that performed the delete.
    """
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
    await db_session.commit()
    user_id = user.id

    migrator_engine = create_async_engine(migrator_database_url)
    try:
        async with migrator_engine.begin() as connection:
            await connection.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    finally:
        await migrator_engine.dispose()

    # The delete above happened on a different connection entirely; db_session's
    # identity map still holds the pre-delete instances unless told otherwise.
    db_session.expire_all()

    assert await db_session.get(Profile, user_id) is None
    assert (
        await db_session.execute(select(UserIdentity).where(UserIdentity.user_id == user_id))
    ).first() is None
    assert (
        await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id))
    ).first() is None
    assert (
        await db_session.execute(
            select(PasswordResetCode).where(PasswordResetCode.user_id == user_id)
        )
    ).first() is None
