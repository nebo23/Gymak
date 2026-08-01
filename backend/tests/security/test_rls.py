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

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import ProgrammingError
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


async def test_rls_blocks_cross_user_update_as_zero_rows_not_an_error(
    db_session: AsyncSession,
) -> None:
    """Was named "...update_and_delete..." before the A.5 item 1 role split: gymak_app
    used to hold GRANT ALL, so a cross-user DELETE on profiles was blocked by RLS alone,
    the same as UPDATE. Post-split, gymak_app has no DELETE grant on profiles at all --
    no repository ever deletes a profile row -- so a DELETE now fails at the grant layer
    before RLS is even evaluated (see test_gymak_app_cannot_delete_profiles below, in
    the A.5 item 1 section). That is a *stronger* guarantee, not a weaker one, but it is
    a different mechanism, so it needed its own test rather than living in this one.
    """
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
    # COMMIT, not rollback: if the statement above had actually matched user_a's row,
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


async def test_refresh_tokens_writes_still_scope_to_the_owner(db_session: AsyncSession) -> None:
    """profiles' owner policy is spelled out explicitly in spec 4.7; refresh_tokens' was
    inferred from the same pattern in T-02, since the spec enables RLS on it but only
    shows the CREATE POLICY line for profiles. INSERT/UPDATE/DELETE are unchanged by
    migration 6b18a9095bb4 (see the next test) -- confirm the owner policy still governs
    writes: user_b's session cannot revoke user_a's token.
    """
    user_a = await _insert_user_with_profile(db_session)
    user_b = await _insert_user_with_profile(db_session)
    user_a_id, user_b_id = user_a.id, user_b.id

    # Same WITH CHECK reasoning as _insert_user_with_profile: re-establish app.user_id
    # to match whichever user's own token is being inserted next.
    await set_rls_user(db_session, str(user_a_id))
    db_session.add(
        RefreshToken(
            id=new_id(),
            user_id=user_a_id,
            token_hash="token-hash-a",
            family_id=new_id(),
            expires_at=datetime.now(UTC) + timedelta(days=60),
        )
    )
    await db_session.commit()

    await set_rls_user(db_session, str(user_b_id))
    update_result = cast(
        CursorResult[Any],
        await db_session.execute(
            text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :uid"),
            {"uid": user_a_id},
        ),
    )
    assert update_result.rowcount == 0
    await db_session.commit()

    await set_rls_user(db_session, str(user_a_id))
    revoked_at = (
        await db_session.execute(
            text("SELECT revoked_at FROM refresh_tokens WHERE user_id = :uid"),
            {"uid": user_a_id},
        )
    ).scalar_one_or_none()
    assert revoked_at is None


async def test_refresh_tokens_select_is_permissive_by_design(db_session: AsyncSession) -> None:
    """Migration 6b18a9095bb4 deliberately widens refresh_tokens' SELECT policy to
    `USING (true)`: /auth/refresh must look up a token by hash before it knows which
    user it belongs to (spec 5.5 step 1), and with app.user_id unset the original
    owner-only policy returned zero rows for every lookup -- see
    test_rls_with_no_app_user_id_set_returns_zero_rows_not_all_rows above, which proves
    that failure mode against `profiles`, still ungrouped by design. Confirm the
    widened policy is what's actually in force for refresh_tokens: a row inserted under
    one user is still SELECT-able with app.user_id bound to a *different* user, or
    unset entirely -- the opposite of profiles' behaviour, and intentionally so.
    """
    user_a = await _insert_user_with_profile(db_session)
    user_b = await _insert_user_with_profile(db_session)

    await set_rls_user(db_session, str(user_a.id))
    db_session.add(
        RefreshToken(
            id=new_id(),
            user_id=user_a.id,
            token_hash="token-hash-lookup-a",
            family_id=new_id(),
            expires_at=datetime.now(UTC) + timedelta(days=60),
        )
    )
    await db_session.commit()

    await set_rls_user(db_session, str(user_b.id))
    visible_as_other_user = (
        (
            await db_session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == "token-hash-lookup-a")
            )
        )
        .scalars()
        .all()
    )
    assert [row.user_id for row in visible_as_other_user] == [user_a.id]

    await set_rls_user(db_session, None)
    visible_unset = (
        (
            await db_session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == "token-hash-lookup-a")
            )
        )
        .scalars()
        .all()
    )
    assert [row.user_id for row in visible_unset] == [user_a.id]


# --- A.5 item 1: gymak_app holds DML only, never DDL -----------------------------------
#
# Migration 737d03a7c353 (see its docstring) transfers table ownership to gymak_migrator
# and leaves gymak_app with table-level GRANTs only. These tests prove that split holds
# for the exact attack the task names: before it, the role that ran the migration also
# served the application, so nothing stopped it from DROPping its own protections.
# Every assertion below runs a real DDL/DCL statement as gymak_app (db_session's
# connection, same role RLS is proven against above) and asserts it is refused, not that
# it merely "still works" -- a control that can never fail is decoration, same reasoning
# as this file's own preamble.


async def test_gymak_app_cannot_create_table(db_session: AsyncSession) -> None:
    with pytest.raises(ProgrammingError, match="permission denied for schema"):
        await db_session.execute(text("CREATE TABLE not_allowed (id int)"))


async def test_gymak_app_cannot_alter_table(db_session: AsyncSession) -> None:
    with pytest.raises(ProgrammingError, match="must be owner of table"):
        await db_session.execute(text("ALTER TABLE profiles ADD COLUMN not_allowed int"))


async def test_gymak_app_cannot_drop_policy(db_session: AsyncSession) -> None:
    """The exact scenario A.5 item 1 named: before the split, gymak_app owned this
    table (it ran the migration that created it), so it could DROP POLICY on its own
    RLS barrier at will. gymak_migrator owns it now.
    """
    with pytest.raises(ProgrammingError, match="must be owner of relation"):
        await db_session.execute(text("DROP POLICY p_profiles_owner ON profiles"))


async def test_gymak_app_cannot_disable_force_row_level_security(
    db_session: AsyncSession,
) -> None:
    """The other half of the same scenario: spec 4.7's own comment on FORCE says
    Postgres exempts a table's OWNER from its own policies. Before the split, gymak_app
    was that owner, so `ALTER TABLE ... NO FORCE` was one statement away from making
    every policy in this file a no-op for its own connection.
    """
    with pytest.raises(ProgrammingError, match="must be owner of table"):
        await db_session.execute(text("ALTER TABLE profiles NO FORCE ROW LEVEL SECURITY"))


async def test_gymak_app_cannot_update_audit_log(db_session: AsyncSession) -> None:
    """Spec 4.6: the app role holds INSERT and SELECT only on audit_log. Before the
    split this was also true by GRANT, but gymak_app *owned* audit_log (having created
    it), so it could always re-GRANT itself UPDATE/DELETE regardless of any prior
    REVOKE -- an owner can always grant on its own object. gymak_migrator owns it now.
    """
    with pytest.raises(ProgrammingError, match="permission denied for table audit_log"):
        await db_session.execute(text("UPDATE audit_log SET action = 'tampered'"))


async def test_gymak_app_cannot_delete_audit_log(db_session: AsyncSession) -> None:
    with pytest.raises(ProgrammingError, match="permission denied for table audit_log"):
        await db_session.execute(text("DELETE FROM audit_log"))


async def test_gymak_app_cannot_delete_profiles(db_session: AsyncSession) -> None:
    """profile_repo.py never deletes a row (§4.3: onboarding is captured once, edited
    afterwards, never removed independently of the user), so migration 737d03a7c353
    grants no DELETE on profiles at all -- scoped to what is actually used, per A.5 item
    1's "the tables that need each," not "every table gets every verb." A cross-user
    DELETE therefore now fails here, at the grant layer, before RLS is even reached --
    see test_rls_blocks_cross_user_update_as_zero_rows_not_an_error's docstring for why
    that test no longer also covers DELETE.
    """
    with pytest.raises(ProgrammingError, match="permission denied for table profiles"):
        await db_session.execute(text("DELETE FROM profiles"))
