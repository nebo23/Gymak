"""RLS proof: T-01b built set_rls_user (transaction-scoped app.user_id) and the
migration enables RLS with an owner policy on profiles and refresh_tokens, but nothing
had ever exercised a real policy end to end until now. Runs under the gymak_app
non-superuser role (see conftest.py) -- RLS is bypassed entirely for superusers and
BYPASSRLS roles regardless of what any policy says, so anything less would be a false
guarantee, which is exactly why database.py now asserts against that at import time.

A.5 item 13: every fixture below seeds its rows over a superuser connection
(`superuser_database_url`), which bypasses RLS unconditionally -- regardless of
whether the policy under test is correct, broken, or missing entirely. The app-role
`db_session` connection (the one RLS actually applies to) is used only for the
read/update/insert each test is actually about, so a broken policy shows up as a
failed assertion, never as a crash while building the fixture.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.ids import new_id
from app.database import set_rls_user
from app.models import (
    BodyWeightEntry,
    Profile,
    Program,
    ProgramDay,
    ProgramExercise,
    RefreshToken,
    WorkoutSession,
    WorkoutSet,
)


def _new_email() -> str:
    return f"{uuid.uuid4()}@example.com"


async def _seed_user_with_profile(
    superuser_database_url: str, *, name: str = "Test User"
) -> uuid.UUID:
    """A.5 item 13: insert a user + profile with plain SQL over a superuser
    connection. Superuser connections bypass row-level security unconditionally in
    Postgres -- FORCE or not -- so this insert succeeds whether profiles' owner
    policy is correct, broken, or absent, and no test below can fail here because of
    the very mechanism it exists to exercise. A dedicated, disposable engine (never
    the shared app engine) mirrors the pattern `database._fetch_connection_role_
    privileges` already uses for the same reason: a one-off probe connection must
    never linger in a pool bound to this test's event loop.
    """
    user_id = new_id()
    engine = create_async_engine(superuser_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, email_verified) "
                    "VALUES (:id, :email, 'hash', true)"
                ),
                {"id": user_id, "email": _new_email()},
            )
            await conn.execute(
                text(
                    "INSERT INTO profiles "
                    "(user_id, name, gender, birth_date, height_cm, goal, experience_level) "
                    "VALUES (:user_id, :name, 'male', :birth_date, 175, 'maintain', 'beginner')"
                ),
                {"user_id": user_id, "name": name, "birth_date": date(1995, 1, 1)},
            )
    finally:
        await engine.dispose()
    return user_id


async def _seed_refresh_token(
    superuser_database_url: str, user_id: uuid.UUID, *, token_hash: str
) -> None:
    """Same rationale as `_seed_user_with_profile`: the refresh_tokens tests below are
    about what the owner policy does to a SELECT or UPDATE against an *existing* row,
    not about whether the app role can INSERT one -- so the row is seeded past RLS
    entirely rather than through a `set_rls_user`-bound app-role insert.
    """
    engine = create_async_engine(superuser_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO refresh_tokens (id, user_id, token_hash, family_id, expires_at) "
                    "VALUES (:id, :user_id, :token_hash, :family_id, :expires_at)"
                ),
                {
                    "id": new_id(),
                    "user_id": user_id,
                    "token_hash": token_hash,
                    "family_id": new_id(),
                    "expires_at": datetime.now(UTC) + timedelta(days=60),
                },
            )
    finally:
        await engine.dispose()


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


async def test_rls_scopes_select_to_the_current_user_only(
    superuser_database_url: str, db_session: AsyncSession
) -> None:
    user_a_id = await _seed_user_with_profile(superuser_database_url)
    user_b_id = await _seed_user_with_profile(superuser_database_url)

    await set_rls_user(db_session, str(user_b_id))
    visible = (await db_session.execute(select(Profile))).scalars().all()

    assert [row.user_id for row in visible] == [user_b_id]
    assert user_a_id not in {row.user_id for row in visible}


async def test_rls_blocks_cross_user_update_as_zero_rows_not_an_error(
    superuser_database_url: str, db_session: AsyncSession
) -> None:
    """Was named "...update_and_delete..." before the A.5 item 1 role split: gymak_app
    used to hold GRANT ALL, so a cross-user DELETE on profiles was blocked by RLS alone,
    the same as UPDATE. Post-split, gymak_app has no DELETE grant on profiles at all --
    no repository ever deletes a profile row -- so a DELETE now fails at the grant layer
    before RLS is even evaluated (see test_gymak_app_cannot_delete_profiles below, in
    the A.5 item 1 section). That is a *stronger* guarantee, not a weaker one, but it is
    a different mechanism, so it needed its own test rather than living in this one.
    """
    user_a_id = await _seed_user_with_profile(superuser_database_url)
    user_b_id = await _seed_user_with_profile(superuser_database_url)

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
    superuser_database_url: str, db_session: AsyncSession
) -> None:
    """The failure mode that matters: if app.user_id is missing entirely and the policy
    evaluates permissively, RLS is decoration, not a barrier. current_setting(..., true)
    returns NULL when the variable was never set, and `user_id = NULL` is never true in
    SQL -- this confirms that holds against a real policy, not just in theory."""
    await _seed_user_with_profile(superuser_database_url)
    await _seed_user_with_profile(superuser_database_url)

    visible = (await db_session.execute(select(Profile))).scalars().all()
    assert visible == []


async def test_refresh_tokens_writes_still_scope_to_the_owner(
    superuser_database_url: str, db_session: AsyncSession
) -> None:
    """profiles' owner policy is spelled out explicitly in spec 4.7; refresh_tokens' was
    inferred from the same pattern in T-02, since the spec enables RLS on it but only
    shows the CREATE POLICY line for profiles. INSERT/UPDATE/DELETE are unchanged by
    migration 6b18a9095bb4 (see the next test) -- confirm the owner policy still governs
    writes: user_b's session cannot revoke user_a's token.

    The initial token is seeded past RLS (A.5 item 13): this test is about the UPDATE
    side of the owner policy, not the INSERT side, so the row's existence must not
    depend on the app role satisfying refresh_tokens' WITH CHECK.
    """
    user_a_id = await _seed_user_with_profile(superuser_database_url)
    user_b_id = await _seed_user_with_profile(superuser_database_url)
    await _seed_refresh_token(superuser_database_url, user_a_id, token_hash="token-hash-a")

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


async def test_refresh_tokens_select_is_permissive_by_design(
    superuser_database_url: str, db_session: AsyncSession
) -> None:
    """Migration 6b18a9095bb4 deliberately widens refresh_tokens' SELECT policy to
    `USING (true)`: /auth/refresh must look up a token by hash before it knows which
    user it belongs to (spec 5.5 step 1), and with app.user_id unset the original
    owner-only policy returned zero rows for every lookup -- see
    test_rls_with_no_app_user_id_set_returns_zero_rows_not_all_rows above, which proves
    that failure mode against `profiles`, still ungrouped by design. Confirm the
    widened policy is what's actually in force for refresh_tokens: a row inserted under
    one user is still SELECT-able with app.user_id bound to a *different* user, or
    unset entirely -- the opposite of profiles' behaviour, and intentionally so.

    A.5 item 13: the row is seeded past RLS -- this test is about SELECT permissiveness,
    not about whether an app-role INSERT under the owner policy would have succeeded.
    """
    user_a_id = await _seed_user_with_profile(superuser_database_url)
    user_b_id = await _seed_user_with_profile(superuser_database_url)
    await _seed_refresh_token(superuser_database_url, user_a_id, token_hash="token-hash-lookup-a")

    await set_rls_user(db_session, str(user_b_id))
    visible_as_other_user = (
        (
            await db_session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == "token-hash-lookup-a")
            )
        )
        .scalars()
        .all()
    )
    assert [row.user_id for row in visible_as_other_user] == [user_a_id]

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
    assert [row.user_id for row in visible_unset] == [user_a_id]


async def test_dropping_the_owner_policy_makes_the_barrier_provably_load_bearing(
    migrator_database_url: str, superuser_database_url: str, db_session: AsyncSession
) -> None:
    """A.5 item 13, the important half of that task. Every assertion above proves a
    permitted read succeeds or a forbidden one returns zero rows -- which looks
    identical whether the owner policy is doing that or was never wired up at all
    (spec 6.5: "test that a control prevents, not that it functions ... An RLS test
    that can never fail is decoration"). This is the one test that removes the barrier,
    shows the read every test above relies on being blocked now leaks, then puts the
    barrier back -- so this file provably fails if `p_profiles_owner` is ever dropped
    from the real migration, per spec 11.1 and 11.3 item 3.

    A bare DROP POLICY here would not demonstrate a leak: Postgres's documented
    behaviour for a table with ENABLE ROW LEVEL SECURITY and zero policies is
    default-deny for every command and every role that does not bypass RLS -- that
    would hide the row from its own legitimate owner too, not open it up, so "the
    forbidden read now succeeds" would never hold. So this drops the real policy and
    installs a deliberately permissive stand-in (`USING (true)`) instead of leaving
    none -- matching the historical T-01b bug class (a policy present but not actually
    restricting anything), which is the failure this test needs to reproduce. The
    original expression is restored from spec 4.7 in a `finally` block regardless of
    outcome, since the testcontainer is session-scoped and no later test in this file
    may run against a permanently weakened policy.
    """
    owner_id = await _seed_user_with_profile(superuser_database_url, name="Policy Drop Owner")
    intruder_id = uuid.uuid4()

    migrator_engine = create_async_engine(migrator_database_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_profiles_owner ON profiles"))
            await conn.execute(text("CREATE POLICY p_profiles_owner ON profiles USING (true)"))

        # Barrier gone: a session bound to an unrelated identity can now read the
        # owner's row -- the exact read every test above relies on coming back empty.
        await set_rls_user(db_session, str(intruder_id))
        leaked = (
            (await db_session.execute(select(Profile).where(Profile.user_id == owner_id)))
            .scalars()
            .all()
        )
        # Commit before the finally block's DROP POLICY below: db_session's read left
        # its transaction open (idle in transaction), holding a lock that would
        # otherwise deadlock against the ACCESS EXCLUSIVE lock DROP POLICY needs on
        # the same table -- confirmed against a real hang, not assumed. Committing
        # here, before the assertion, means the lock is released even if the
        # assertion below fails.
        await db_session.commit()
        assert [row.user_id for row in leaked] == [owner_id]
    finally:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_profiles_owner ON profiles"))
            await conn.execute(
                text(
                    "CREATE POLICY p_profiles_owner ON profiles USING "
                    "(user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)"
                )
            )
        await migrator_engine.dispose()

    # Restored: the same read, from the same unrelated identity, is blocked again --
    # confirming the restore actually took effect rather than merely not raising.
    await set_rls_user(db_session, str(intruder_id))
    still_hidden = (
        (await db_session.execute(select(Profile).where(Profile.user_id == owner_id)))
        .scalars()
        .all()
    )
    assert still_hidden == []


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


# --- Phase 2 (T-15): RLS on the six new user-owned tables, plus exercises' exception ---
#
# P2-ADR-09 / spec §4.10. `programs`, `workout_sessions`, and `body_weight_entries` carry
# `user_id` directly, so their proofs mirror this file's own `profiles` pattern above.
# `program_days`, `program_exercises`, and `workout_sets` carry no `user_id` of their
# own -- ownership reads through a parent chain -- so their proofs use the same
# drop-a-permissive-stand-in technique but against the EXISTS policy shape. Every seed
# below goes through db_session under the OWNER's own app.user_id, not past RLS: unlike
# Phase 1's profiles/refresh_tokens (seeded pre-auth, A.5 item 13), every Phase 2 table
# gymak_app writes to at all is written by an authenticated user with app.user_id already
# bound -- there is no pre-auth gap here to route around.


def _program_kwargs(user_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "id": new_id(),
        "user_id": user_id,
        "days_per_week": 4,
        "split_type": "upper_lower",
        "goal": "gain",
        "experience_level": "beginner",
        "generator_version": 1,
    }
    kwargs.update(overrides)
    return kwargs


def _program_day_kwargs(program_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "id": new_id(),
        "program_id": program_id,
        "day_index": 1,
        "label_key": "plan.day.upper",
        "focus_muscles": ["chest", "back"],
    }
    kwargs.update(overrides)
    return kwargs


def _program_exercise_kwargs(
    program_day_id: uuid.UUID, exercise_id: uuid.UUID, **overrides: object
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "id": new_id(),
        "program_day_id": program_day_id,
        "exercise_id": exercise_id,
        "position": 1,
        "target_sets": 3,
        "target_reps_min": 8,
        "target_reps_max": 12,
        "rest_seconds": 90,
    }
    kwargs.update(overrides)
    return kwargs


def _workout_session_kwargs(user_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "id": new_id(),
        "user_id": user_id,
        "status": "in_progress",
        "local_date": date.today(),
    }
    kwargs.update(overrides)
    return kwargs


def _workout_set_kwargs(
    session_id: uuid.UUID, exercise_id: uuid.UUID, **overrides: object
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "id": new_id(),
        "session_id": session_id,
        "exercise_id": exercise_id,
        "set_index": 1,
        "reps": 8,
        "weight_kg": 60,
    }
    kwargs.update(overrides)
    return kwargs


def _body_weight_kwargs(user_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "id": new_id(),
        "user_id": user_id,
        "measured_on": date.today(),
        "weight_kg": 75,
    }
    kwargs.update(overrides)
    return kwargs


_INSERT_EXERCISE_SQL = text(
    "INSERT INTO exercises (id, slug, name_en, name_ar, primary_muscle, equipment, "
    "movement_pattern, is_compound, difficulty, instructions_en, instructions_ar) "
    "VALUES (:id, :slug, 'Test Exercise', 'تمرين تجريبي', 'chest', 'barbell', "
    "'horizontal_push', true, 'beginner', 'Do the thing.', 'قم بالتمرين.')"
)


async def _insert_exercise(migrator_database_url: str) -> uuid.UUID:
    """exercises is granted SELECT only to gymak_app (§4.10) -- seeded over a dedicated
    migrator connection, the same rationale as tests/unit/test_models.py's identical
    helper: no repository or fixture using the app role can ever INSERT here.
    """
    exercise_id = new_id()
    engine = create_async_engine(migrator_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                _INSERT_EXERCISE_SQL, {"id": exercise_id, "slug": f"ex-{uuid.uuid4()}"}
            )
    finally:
        await engine.dispose()
    return exercise_id


_NEW_RLS_TABLES = (
    "programs",
    "program_days",
    "program_exercises",
    "workout_sessions",
    "workout_sets",
    "body_weight_entries",
)

_OWNER_POLICY_NAMES = {
    "programs": "p_programs_owner",
    "program_days": "p_program_days_owner",
    "program_exercises": "p_program_exercises_owner",
    "workout_sessions": "p_workout_sessions_owner",
    "workout_sets": "p_workout_sets_owner",
    "body_weight_entries": "p_body_weight_entries_owner",
}

_DIRECT_OWNER_POLICY_SQL = {
    table: (
        f"CREATE POLICY {policy} ON {table} "
        "USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid) "
        "WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)"
    )
    for table, policy in _OWNER_POLICY_NAMES.items()
    if table in ("programs", "workout_sessions", "body_weight_entries")
}

_PROGRAM_DAYS_OWNER_POLICY_SQL = (
    "CREATE POLICY p_program_days_owner ON program_days "
    "USING (EXISTS (SELECT 1 FROM programs p WHERE p.id = program_days.program_id "
    "AND p.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)) "
    "WITH CHECK (EXISTS (SELECT 1 FROM programs p WHERE p.id = program_days.program_id "
    "AND p.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid))"
)

_PROGRAM_EXERCISES_OWNER_POLICY_SQL = (
    "CREATE POLICY p_program_exercises_owner ON program_exercises "
    "USING (EXISTS (SELECT 1 FROM program_days d JOIN programs p ON p.id = d.program_id "
    "WHERE d.id = program_exercises.program_day_id "
    "AND p.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)) "
    "WITH CHECK (EXISTS (SELECT 1 FROM program_days d JOIN programs p ON p.id = d.program_id "
    "WHERE d.id = program_exercises.program_day_id "
    "AND p.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid))"
)

# §4.10, verbatim -- the one policy the spec itself spells out in full.
_WORKOUT_SETS_OWNER_POLICY_SQL = (
    "CREATE POLICY p_workout_sets_owner ON workout_sets "
    "USING (EXISTS (SELECT 1 FROM workout_sessions s WHERE s.id = workout_sets.session_id "
    "AND s.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)) "
    "WITH CHECK (EXISTS (SELECT 1 FROM workout_sessions s WHERE s.id = workout_sets.session_id "
    "AND s.user_id = NULLIF(current_setting('app.user_id', true), '')::uuid))"
)


async def test_new_tables_have_rls_enabled_and_forced(db_session: AsyncSession) -> None:
    """Same guard as this file's own preamble test, extended to the six Phase 2 tables:
    ENABLE without FORCE would silently exempt gymak_migrator (their owner) from its own
    policies, which is exactly the historical bug class A.5 item 1 closed for Phase 1.
    """
    rows = (
        await db_session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY(:names) ORDER BY relname"
            ),
            {"names": list(_NEW_RLS_TABLES)},
        )
    ).all()
    assert [(row.relname, row.relrowsecurity, row.relforcerowsecurity) for row in rows] == [
        (name, True, True) for name in sorted(_NEW_RLS_TABLES)
    ]


async def test_exercises_has_no_rls_at_all(db_session: AsyncSession) -> None:
    """§4.10's stated exception: exercises is public reference data with no user_id --
    SELECT granted, no policy, and RLS never enabled on it at all. Asserted explicitly
    so the absence reads as a deliberate decision, not an oversight (spec 10.1: 'exercises
    is readable by any authenticated user and writable by none')."""
    row = (
        await db_session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'exercises'"
            )
        )
    ).one()
    assert (row.relrowsecurity, row.relforcerowsecurity) == (False, False)


async def test_exercises_is_readable_with_no_app_user_id_bound(db_session: AsyncSession) -> None:
    """No policy means no owner column to scope by -- a plain GRANT SELECT, readable
    regardless of whether app.user_id is bound at all."""
    result = await db_session.execute(text("SELECT count(*) FROM exercises"))
    assert result.scalar_one() >= 0  # the point is that this does not raise


async def test_gymak_app_cannot_write_to_exercises(db_session: AsyncSession) -> None:
    with pytest.raises(ProgrammingError, match="permission denied for table exercises"):
        await db_session.execute(
            text(
                "INSERT INTO exercises (id, slug, name_en, name_ar, primary_muscle, "
                "equipment, movement_pattern, is_compound, difficulty, instructions_en, "
                "instructions_ar) VALUES (:id, 'hijack', 'x', 'x', 'chest', 'barbell', "
                "'horizontal_push', true, 'beginner', 'x', 'x')"
            ),
            {"id": new_id()},
        )


async def test_gymak_app_cannot_update_exercises(db_session: AsyncSession) -> None:
    with pytest.raises(ProgrammingError, match="permission denied for table exercises"):
        await db_session.execute(text("UPDATE exercises SET is_active = false"))


async def test_gymak_app_cannot_delete_exercises(db_session: AsyncSession) -> None:
    with pytest.raises(ProgrammingError, match="permission denied for table exercises"):
        await db_session.execute(text("DELETE FROM exercises"))


async def test_gymak_app_cannot_create_policy_on_any_new_table(db_session: AsyncSession) -> None:
    """A.5 item 1's exact scenario, extended to Phase 2: gymak_migrator owns every table
    created in migration 88d15c15b877, so gymak_app -- DML-only from the split onward --
    must not be able to install a policy of its own on any of them."""
    for table in _NEW_RLS_TABLES:
        with pytest.raises(ProgrammingError, match="must be owner of table"):
            await db_session.execute(text(f"CREATE POLICY p_hijack ON {table} USING (true)"))
        await db_session.rollback()


async def test_gymak_app_cannot_drop_policy_on_any_new_table(db_session: AsyncSession) -> None:
    for table, policy in _OWNER_POLICY_NAMES.items():
        with pytest.raises(ProgrammingError, match="must be owner of relation"):
            await db_session.execute(text(f"DROP POLICY {policy} ON {table}"))
        await db_session.rollback()


async def test_gymak_app_cannot_alter_any_new_table(db_session: AsyncSession) -> None:
    for table in _NEW_RLS_TABLES:
        with pytest.raises(ProgrammingError, match="must be owner of table"):
            await db_session.execute(text(f"ALTER TABLE {table} ADD COLUMN not_allowed int"))
        await db_session.rollback()


async def test_gymak_app_cannot_disable_force_row_level_security_on_any_new_table(
    db_session: AsyncSession,
) -> None:
    for table in _NEW_RLS_TABLES:
        with pytest.raises(ProgrammingError, match="must be owner of table"):
            await db_session.execute(text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        await db_session.rollback()


async def test_dropping_programs_owner_policy_leaks_across_tenants(
    migrator_database_url: str, superuser_database_url: str, db_session: AsyncSession
) -> None:
    owner_id = await _seed_user_with_profile(superuser_database_url, name="Programs Owner")
    await set_rls_user(db_session, str(owner_id))
    program = Program(**_program_kwargs(owner_id))
    db_session.add(program)
    # id is client-side (default=new_id, spec P1-ADR-06), so it is already populated
    # before flush -- captured here rather than via a post-commit SELECT, because after
    # commit() clears the transaction-scoped app.user_id (set_rls_user's own docstring),
    # a SELECT as the very owner who just inserted it would come back empty until
    # re-bound, which is not what this line is testing.
    program_id = program.id
    await db_session.commit()
    intruder_id = uuid.uuid4()

    migrator_engine = create_async_engine(migrator_database_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_programs_owner ON programs"))
            await conn.execute(text("CREATE POLICY p_programs_owner ON programs USING (true)"))

        await set_rls_user(db_session, str(intruder_id))
        leaked = (
            (await db_session.execute(select(Program).where(Program.id == program_id)))
            .scalars()
            .all()
        )
        await db_session.commit()
        assert [row.id for row in leaked] == [program_id]
    finally:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_programs_owner ON programs"))
            await conn.execute(text(_DIRECT_OWNER_POLICY_SQL["programs"]))
        await migrator_engine.dispose()

    await set_rls_user(db_session, str(intruder_id))
    still_hidden = (
        (await db_session.execute(select(Program).where(Program.id == program_id))).scalars().all()
    )
    assert still_hidden == []


async def test_dropping_workout_sessions_owner_policy_leaks_across_tenants(
    migrator_database_url: str, superuser_database_url: str, db_session: AsyncSession
) -> None:
    owner_id = await _seed_user_with_profile(superuser_database_url, name="Sessions Owner")
    await set_rls_user(db_session, str(owner_id))
    session = WorkoutSession(**_workout_session_kwargs(owner_id))
    db_session.add(session)
    session_id = session.id  # see the identical comment in the programs test above
    await db_session.commit()
    intruder_id = uuid.uuid4()

    migrator_engine = create_async_engine(migrator_database_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_workout_sessions_owner ON workout_sessions"))
            await conn.execute(
                text("CREATE POLICY p_workout_sessions_owner ON workout_sessions USING (true)")
            )

        await set_rls_user(db_session, str(intruder_id))
        leaked = (
            (
                await db_session.execute(
                    select(WorkoutSession).where(WorkoutSession.id == session_id)
                )
            )
            .scalars()
            .all()
        )
        await db_session.commit()
        assert [row.id for row in leaked] == [session_id]
    finally:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_workout_sessions_owner ON workout_sessions"))
            await conn.execute(text(_DIRECT_OWNER_POLICY_SQL["workout_sessions"]))
        await migrator_engine.dispose()

    await set_rls_user(db_session, str(intruder_id))
    still_hidden = (
        (await db_session.execute(select(WorkoutSession).where(WorkoutSession.id == session_id)))
        .scalars()
        .all()
    )
    assert still_hidden == []


async def test_dropping_body_weight_entries_owner_policy_leaks_across_tenants(
    migrator_database_url: str, superuser_database_url: str, db_session: AsyncSession
) -> None:
    owner_id = await _seed_user_with_profile(superuser_database_url, name="Weight Owner")
    await set_rls_user(db_session, str(owner_id))
    entry = BodyWeightEntry(**_body_weight_kwargs(owner_id))
    db_session.add(entry)
    entry_id = entry.id  # see the identical comment in the programs test above
    await db_session.commit()
    intruder_id = uuid.uuid4()

    migrator_engine = create_async_engine(migrator_database_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(
                text("DROP POLICY p_body_weight_entries_owner ON body_weight_entries")
            )
            await conn.execute(
                text(
                    "CREATE POLICY p_body_weight_entries_owner ON body_weight_entries USING (true)"
                )
            )

        await set_rls_user(db_session, str(intruder_id))
        leaked = (
            (
                await db_session.execute(
                    select(BodyWeightEntry).where(BodyWeightEntry.id == entry_id)
                )
            )
            .scalars()
            .all()
        )
        await db_session.commit()
        assert [row.id for row in leaked] == [entry_id]
    finally:
        async with migrator_engine.begin() as conn:
            await conn.execute(
                text("DROP POLICY p_body_weight_entries_owner ON body_weight_entries")
            )
            await conn.execute(text(_DIRECT_OWNER_POLICY_SQL["body_weight_entries"]))
        await migrator_engine.dispose()

    await set_rls_user(db_session, str(intruder_id))
    still_hidden = (
        (await db_session.execute(select(BodyWeightEntry).where(BodyWeightEntry.id == entry_id)))
        .scalars()
        .all()
    )
    assert still_hidden == []


async def test_dropping_program_days_owner_policy_leaks_across_tenants(
    migrator_database_url: str, superuser_database_url: str, db_session: AsyncSession
) -> None:
    """program_days carries no user_id -- ownership reads through program_id (P2-ADR-09).
    The stand-in policy below must still be permissive by row content, not by column
    absence: USING (true) is the same 'looks protective but isn't' shape this file's
    profiles test uses, applied to the EXISTS-policy tables.
    """
    owner_id = await _seed_user_with_profile(superuser_database_url, name="Program Days Owner")
    await set_rls_user(db_session, str(owner_id))
    program = Program(**_program_kwargs(owner_id))
    db_session.add(program)
    await db_session.flush()
    program_day = ProgramDay(**_program_day_kwargs(program.id))
    db_session.add(program_day)
    program_day_id = program_day.id  # see the identical comment in the programs test above
    await db_session.commit()
    intruder_id = uuid.uuid4()

    migrator_engine = create_async_engine(migrator_database_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_program_days_owner ON program_days"))
            await conn.execute(
                text("CREATE POLICY p_program_days_owner ON program_days USING (true)")
            )

        await set_rls_user(db_session, str(intruder_id))
        leaked = (
            (await db_session.execute(select(ProgramDay).where(ProgramDay.id == program_day_id)))
            .scalars()
            .all()
        )
        await db_session.commit()
        assert [row.id for row in leaked] == [program_day_id]
    finally:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_program_days_owner ON program_days"))
            await conn.execute(text(_PROGRAM_DAYS_OWNER_POLICY_SQL))
        await migrator_engine.dispose()

    await set_rls_user(db_session, str(intruder_id))
    still_hidden = (
        (await db_session.execute(select(ProgramDay).where(ProgramDay.id == program_day_id)))
        .scalars()
        .all()
    )
    assert still_hidden == []


async def test_dropping_program_exercises_owner_policy_leaks_across_tenants(
    migrator_database_url: str, superuser_database_url: str, db_session: AsyncSession
) -> None:
    """program_exercises' ownership chain is two hops deep (program_day_id -> program_id
    -> user_id) -- the longest in Phase 2, and the one most likely to have a typo'd join.
    """
    owner_id = await _seed_user_with_profile(superuser_database_url, name="Program Ex Owner")
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(owner_id))
    program = Program(**_program_kwargs(owner_id))
    db_session.add(program)
    await db_session.flush()
    program_day = ProgramDay(**_program_day_kwargs(program.id))
    db_session.add(program_day)
    await db_session.flush()
    program_exercise = ProgramExercise(**_program_exercise_kwargs(program_day.id, exercise_id))
    db_session.add(program_exercise)
    program_exercise_id = program_exercise.id  # see the comment in the programs test above
    await db_session.commit()
    intruder_id = uuid.uuid4()

    migrator_engine = create_async_engine(migrator_database_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_program_exercises_owner ON program_exercises"))
            await conn.execute(
                text("CREATE POLICY p_program_exercises_owner ON program_exercises USING (true)")
            )

        await set_rls_user(db_session, str(intruder_id))
        leaked = (
            (
                await db_session.execute(
                    select(ProgramExercise).where(ProgramExercise.id == program_exercise_id)
                )
            )
            .scalars()
            .all()
        )
        await db_session.commit()
        assert [row.id for row in leaked] == [program_exercise_id]
    finally:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_program_exercises_owner ON program_exercises"))
            await conn.execute(text(_PROGRAM_EXERCISES_OWNER_POLICY_SQL))
        await migrator_engine.dispose()

    await set_rls_user(db_session, str(intruder_id))
    still_hidden = (
        (
            await db_session.execute(
                select(ProgramExercise).where(ProgramExercise.id == program_exercise_id)
            )
        )
        .scalars()
        .all()
    )
    assert still_hidden == []


async def test_dropping_workout_sets_owner_policy_leaks_across_tenants(
    migrator_database_url: str, superuser_database_url: str, db_session: AsyncSession
) -> None:
    """§4.10, verbatim policy. P2-ADR-09: 'the cross-tenant test must prove that a set
    belonging to another user's session is invisible, not merely that the session is' --
    this is that proof for the load-bearing half; the direct by-id lookup half is
    test_workout_set_in_another_users_session_is_invisible_even_by_its_own_id below.
    """
    owner_id = await _seed_user_with_profile(superuser_database_url, name="Sets Owner")
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(owner_id))
    session_row = WorkoutSession(**_workout_session_kwargs(owner_id))
    db_session.add(session_row)
    await db_session.flush()
    workout_set = WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id))
    db_session.add(workout_set)
    set_id = workout_set.id  # see the comment in the programs test above
    await db_session.commit()
    intruder_id = uuid.uuid4()

    migrator_engine = create_async_engine(migrator_database_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_workout_sets_owner ON workout_sets"))
            await conn.execute(
                text("CREATE POLICY p_workout_sets_owner ON workout_sets USING (true)")
            )

        # get() checks the session's identity map before it checks the database, and
        # workout_set is already in it from the insert above -- without expiring it
        # first, get() would return the cached instance without a query ever reaching
        # RLS, making every assertion below true regardless of what the policy says.
        db_session.expire_all()
        await set_rls_user(db_session, str(intruder_id))
        leaked = await db_session.get(WorkoutSet, set_id)
        await db_session.commit()
        assert leaked is not None
        assert leaked.id == set_id
    finally:
        async with migrator_engine.begin() as conn:
            await conn.execute(text("DROP POLICY p_workout_sets_owner ON workout_sets"))
            await conn.execute(text(_WORKOUT_SETS_OWNER_POLICY_SQL))
        await migrator_engine.dispose()

    db_session.expire_all()
    await set_rls_user(db_session, str(intruder_id))
    still_hidden = await db_session.get(WorkoutSet, set_id)
    assert still_hidden is None


async def test_workout_set_in_another_users_session_is_invisible_even_by_its_own_id(
    superuser_database_url: str, migrator_database_url: str, db_session: AsyncSession
) -> None:
    """P2-ADR-09's exact wording, with the real (undropped) policy in force: a set
    belonging to another user's session is invisible looked up directly by its own
    primary key, not merely absent from a list query that could hide the gap behind an
    unrelated WHERE clause.
    """
    owner_id = await _seed_user_with_profile(superuser_database_url, name="Real Set Owner")
    intruder_id = await _seed_user_with_profile(superuser_database_url, name="Real Set Intruder")
    exercise_id = await _insert_exercise(migrator_database_url)

    await set_rls_user(db_session, str(owner_id))
    session_row = WorkoutSession(**_workout_session_kwargs(owner_id))
    db_session.add(session_row)
    await db_session.flush()
    workout_set = WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id))
    db_session.add(workout_set)
    set_id = workout_set.id  # see the comment in the programs test above
    await db_session.commit()

    # See the identity-map comment in test_dropping_workout_sets_owner_policy_leaks_
    # across_tenants above -- without this, get() never reaches the database at all.
    db_session.expire_all()
    await set_rls_user(db_session, str(intruder_id))
    invisible = await db_session.get(WorkoutSet, set_id)
    assert invisible is None
