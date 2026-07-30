"""RLS proof: T-01b built set_rls_user (transaction-scoped app.user_id) and the
migration enables RLS with an owner policy on profiles and refresh_tokens, but nothing
had ever exercised a real policy end to end until now. Runs under the gymak_app
non-superuser role (see conftest.py) -- RLS is bypassed entirely for superusers and
BYPASSRLS roles regardless of what any policy says, so anything less would be a false
guarantee, which is exactly why database.py now asserts against that at import time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.database import set_rls_user
from app.models import Profile, RefreshToken, User


def _new_email() -> str:
    return f"{uuid.uuid4()}@example.com"


async def _insert_user_with_profile(session: AsyncSession, *, name: str = "Test User") -> User:
    user = User(id=new_id(), email=_new_email(), password_hash="hash", email_verified=True)
    session.add(user)
    await session.flush()
    # FORCE ROW LEVEL SECURITY (migration) means even the owner role must satisfy the
    # policy's WITH CHECK to insert -- simulates the real flow, where app.user_id is
    # already set to the acting user (via authentication) before any profile is created.
    await set_rls_user(session, str(user.id))
    session.add(
        Profile(
            user_id=user.id,
            name=name,
            gender="male",
            birth_date=date(1995, 1, 1),
            height_cm=175,
            goal="maintain",
            experience_level="beginner",
        )
    )
    await session.flush()
    return user


async def test_preconditions_that_make_every_other_test_here_meaningful(
    db_session: AsyncSession,
) -> None:
    """Guards the two ways this whole file could silently become a false guarantee.

    If the connection were a superuser or BYPASSRLS role, or if the tables were merely
    ENABLE'd rather than FORCE'd (Postgres exempts a table's owner from its own policies,
    and the app role owns these tables because it runs the migration), then every
    assertion below would pass while enforcing nothing. Both were live failure modes
    during T-02, not hypotheticals -- the FORCE omission was found exactly this way.
    """
    role = (
        await db_session.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
    ).one()
    assert role.rolsuper is False
    assert role.rolbypassrls is False

    forced = (
        await db_session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('profiles', 'refresh_tokens') ORDER BY relname"
            )
        )
    ).all()
    assert [(row.relname, row.relrowsecurity, row.relforcerowsecurity) for row in forced] == [
        ("profiles", True, True),
        ("refresh_tokens", True, True),
    ]


async def test_rls_scopes_select_to_the_current_user_only(db_session: AsyncSession) -> None:
    user_a = await _insert_user_with_profile(db_session)
    user_b = await _insert_user_with_profile(db_session)
    await db_session.commit()

    await set_rls_user(db_session, str(user_b.id))
    visible = (await db_session.execute(select(Profile))).scalars().all()

    assert [row.user_id for row in visible] == [user_b.id]
    assert user_a.id not in {row.user_id for row in visible}


async def test_rls_blocks_cross_user_update_and_delete_as_zero_rows_not_an_error(
    db_session: AsyncSession,
) -> None:
    user_a = await _insert_user_with_profile(db_session)
    user_b = await _insert_user_with_profile(db_session)
    # Plain values, not ORM attributes: the commit boundaries below can expire the
    # instances, and touching an expired attribute afterwards triggers a lazy reload --
    # sync IO from async context, which fails rather than returning the id.
    user_a_id, user_b_id = user_a.id, user_b.id
    await db_session.commit()

    await set_rls_user(db_session, str(user_b_id))
    update_result = cast(
        CursorResult[Any],
        await db_session.execute(
            text("UPDATE profiles SET name = 'hijacked' WHERE user_id = :uid"),
            {"uid": user_a_id},
        ),
    )
    # Zero rows affected, not a permission error -- spec 6.5: "generic 404 over 403 for
    # another user's resource, so the API does not confirm that the record exists."
    # RLS gives that behaviour for free at the database layer.
    assert update_result.rowcount == 0

    delete_result = cast(
        CursorResult[Any],
        await db_session.execute(
            text("DELETE FROM profiles WHERE user_id = :uid"), {"uid": user_a_id}
        ),
    )
    assert delete_result.rowcount == 0
    # COMMIT, not rollback: if either statement above had actually matched user_a's row,
    # committing is what would make that damage stick. Rolling back here would undo it
    # and let this test pass for the wrong reason.
    await db_session.commit()

    # Read back as user_a -- their own row must be intact. RLS applies to every SELECT,
    # primary-key lookups included, so app.user_id has to be user_a's to see it at all.
    # Raw SQL rather than session.get(): get() can be answered from the identity map
    # without touching the database, which would make this assertion vacuous.
    await set_rls_user(db_session, str(user_a_id))
    name_now = (
        await db_session.execute(
            text("SELECT name FROM profiles WHERE user_id = :uid"), {"uid": user_a_id}
        )
    ).scalar_one_or_none()
    assert name_now == "Test User"


async def test_rls_with_no_app_user_id_set_returns_zero_rows_not_all_rows(
    db_session: AsyncSession,
) -> None:
    """The failure mode that matters: if app.user_id is missing entirely and the policy
    evaluates permissively, RLS is decoration, not a barrier. current_setting(..., true)
    returns NULL when the variable was never set, and `user_id = NULL` is never true in
    SQL -- this confirms that holds against a real policy, not just in theory."""
    await _insert_user_with_profile(db_session)
    await _insert_user_with_profile(db_session)
    await db_session.commit()

    visible = (await db_session.execute(select(Profile))).scalars().all()
    assert visible == []


async def test_rls_also_scopes_refresh_tokens(db_session: AsyncSession) -> None:
    """profiles' owner policy is spelled out explicitly in spec 4.7; refresh_tokens' was
    inferred from the same pattern in T-02, since the spec enables RLS on it but only
    shows the CREATE POLICY line for profiles. Confirm the inference actually holds."""
    user_a = await _insert_user_with_profile(db_session)
    user_b = await _insert_user_with_profile(db_session)

    # Same WITH CHECK reasoning as _insert_user_with_profile: re-establish app.user_id
    # to match whichever user's own token is being inserted next.
    await set_rls_user(db_session, str(user_a.id))
    db_session.add(
        RefreshToken(
            id=new_id(),
            user_id=user_a.id,
            token_hash="token-hash-a",
            family_id=new_id(),
            expires_at=datetime.now(UTC) + timedelta(days=60),
        )
    )
    await db_session.flush()

    await set_rls_user(db_session, str(user_b.id))
    db_session.add(
        RefreshToken(
            id=new_id(),
            user_id=user_b.id,
            token_hash="token-hash-b",
            family_id=new_id(),
            expires_at=datetime.now(UTC) + timedelta(days=60),
        )
    )
    await db_session.commit()

    await set_rls_user(db_session, str(user_b.id))
    visible = (await db_session.execute(select(RefreshToken))).scalars().all()

    assert [row.user_id for row in visible] == [user_b.id]
