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
from app.models import (
    BodyWeightEntry,
    PasswordResetCode,
    Profile,
    Program,
    ProgramDay,
    ProgramExercise,
    RefreshToken,
    User,
    UserIdentity,
    WorkoutSession,
    WorkoutSet,
)


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


# --- Phase 2 (T-15): spec §4.3-4.8's seven new tables ---------------------------------
#
# exercises (§4.1, P2-ADR-02) is granted SELECT only to gymak_app -- no repository or
# test using db_session can ever INSERT there, matching production, where only T-16's
# data migration (running as gymak_migrator) populates it. Every exercise row below is
# therefore seeded over a dedicated migrator connection, the same A.5 item 13 pattern
# test_rls.py already uses to seed past a restriction the test itself is not about.


async def _insert_user_with_profile(session: AsyncSession) -> User:
    user = await _insert_user(session)
    session.add(Profile(**_valid_profile_kwargs(user.id)))
    await session.flush()
    return user


_INSERT_EXERCISE_SQL = text(
    "INSERT INTO exercises (id, slug, name_en, name_ar, primary_muscle, equipment, "
    "movement_pattern, is_compound, difficulty, instructions_en, instructions_ar) "
    "VALUES (:id, :slug, 'Test Exercise', 'تمرين تجريبي', :primary_muscle, :equipment, "
    ":movement_pattern, :is_compound, :difficulty, 'Do the thing.', 'قم بالتمرين.')"
)


def _exercise_insert_params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "id": new_id(),
        "slug": f"ex-{uuid.uuid4()}",
        "primary_muscle": "chest",
        "equipment": "barbell",
        "movement_pattern": "horizontal_push",
        "is_compound": True,
        "difficulty": "beginner",
    }
    params.update(overrides)
    return params


async def _insert_exercise(migrator_database_url: str, **overrides: object) -> uuid.UUID:
    params = _exercise_insert_params(**overrides)
    engine = create_async_engine(migrator_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(_INSERT_EXERCISE_SQL, params)
    finally:
        await engine.dispose()
    exercise_id = params["id"]
    assert isinstance(exercise_id, uuid.UUID)
    return exercise_id


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


async def test_profile_timezone_defaults_to_africa_cairo(db_session: AsyncSession) -> None:
    """spec §4.2: 'the default exists only for the rows Phase 1 already created.' The
    Profile ORM mapping does not expose this column (out of scope for T-15's file list --
    profile.py is not one of the files this task may touch; a later task wires timezone
    into profile_service.py's editable fields), so this reads the raw column.
    """
    user = await _insert_user_with_profile(db_session)
    timezone = (
        await db_session.execute(
            text("SELECT timezone FROM profiles WHERE user_id = :uid"), {"uid": user.id}
        )
    ).scalar_one()
    assert timezone == "Africa/Cairo"


async def test_exercise_unknown_primary_muscle_is_rejected(migrator_database_url: str) -> None:
    engine = create_async_engine(migrator_database_url)
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    _INSERT_EXERCISE_SQL, _exercise_insert_params(primary_muscle="not_a_muscle")
                )
    finally:
        await engine.dispose()


async def test_exercise_slug_must_be_unique(migrator_database_url: str) -> None:
    slug = f"ex-{uuid.uuid4()}"
    engine = create_async_engine(migrator_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(_INSERT_EXERCISE_SQL, _exercise_insert_params(slug=slug))
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(_INSERT_EXERCISE_SQL, _exercise_insert_params(slug=slug))
    finally:
        await engine.dispose()


async def test_exercise_referenced_by_program_exercise_cannot_be_deleted(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    """§4.5: exercise_id is ON DELETE RESTRICT, not CASCADE -- P2-ADR-02's guarantee that
    exercises are never deleted, made real rather than merely promised."""
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id)))
    await db_session.flush()
    program_day = (
        await db_session.execute(select(ProgramDay).where(ProgramDay.program_id == program.id))
    ).scalar_one()
    db_session.add(ProgramExercise(**_program_exercise_kwargs(program_day.id, exercise_id)))
    await db_session.commit()

    engine = create_async_engine(migrator_database_url)
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM exercises WHERE id = :eid"), {"eid": exercise_id}
                )
    finally:
        await engine.dispose()


async def test_exercise_referenced_by_workout_set_cannot_be_deleted(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()
    session_row = (
        await db_session.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    ).scalar_one()
    db_session.add(WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id)))
    await db_session.commit()

    engine = create_async_engine(migrator_database_url)
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM exercises WHERE id = :eid"), {"eid": exercise_id}
                )
    finally:
        await engine.dispose()


async def test_program_days_per_week_out_of_range_is_rejected(db_session: AsyncSession) -> None:
    user = await _insert_user_with_profile(db_session)
    db_session.add(Program(**_program_kwargs(user.id, days_per_week=7)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_only_one_current_program_per_user_is_enforced(db_session: AsyncSession) -> None:
    """§4.3: 'Exactly one true per user, enforced by a partial unique index' --
    ux_one_current_program, the same database-level pattern as §4.6's
    ux_one_active_session below."""
    user = await _insert_user_with_profile(db_session)
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    db_session.add(Program(**_program_kwargs(user.id)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_second_current_program_is_allowed_once_the_first_is_superseded(
    db_session: AsyncSession,
) -> None:
    """Proves ux_one_current_program is genuinely partial (WHERE is_current = true),
    not a plain UNIQUE(user_id) that would also reject two superseded rows -- a control
    that can never discriminate is decoration."""
    user = await _insert_user_with_profile(db_session)
    db_session.add(Program(**_program_kwargs(user.id, is_current=False)))
    await db_session.flush()
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()  # must not raise


async def test_program_day_index_out_of_range_is_rejected(db_session: AsyncSession) -> None:
    user = await _insert_user_with_profile(db_session)
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id, day_index=7)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_program_days_day_index_must_be_unique_within_program(
    db_session: AsyncSession,
) -> None:
    user = await _insert_user_with_profile(db_session)
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id, day_index=1)))
    await db_session.flush()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id, day_index=1)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deleting_program_cascades_to_days_and_exercises(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id)))
    await db_session.flush()
    program_day = (
        await db_session.execute(select(ProgramDay).where(ProgramDay.program_id == program.id))
    ).scalar_one()
    db_session.add(ProgramExercise(**_program_exercise_kwargs(program_day.id, exercise_id)))
    await db_session.flush()
    await db_session.commit()
    user_id = user.id
    program_id = program.id
    program_day_id = program_day.id

    # programs is FORCE ROW LEVEL SECURITY, and gymak_migrator (the connection below) is
    # its owner -- FORCE means the owner is subject to its own policy too (confirmed
    # empirically: without binding app.user_id first, this DELETE silently matches zero
    # rows and every assertion below would pass for the wrong reason, the rows never
    # having been touched). Setting it to the row's real owner is what an authorized
    # deletion would require in practice -- gymak_app itself holds no DELETE grant on
    # programs at all (§4.3: old programs are kept), so this path is admin-only anyway.
    engine = create_async_engine(migrator_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
            )
            await conn.execute(text("DELETE FROM programs WHERE id = :pid"), {"pid": program_id})
    finally:
        await engine.dispose()

    # user.id is captured above, before expire_all(): the same object's attributes are
    # expired too, and accessing one synchronously here (outside an awaited call) trips
    # SQLAlchemy's asyncio greenlet guard (MissingGreenlet) -- confirmed empirically.
    db_session.expire_all()
    await set_rls_user(db_session, str(user_id))
    assert (
        await db_session.execute(select(ProgramDay).where(ProgramDay.program_id == program_id))
    ).first() is None
    assert (
        await db_session.execute(
            select(ProgramExercise).where(ProgramExercise.program_day_id == program_day_id)
        )
    ).first() is None


async def test_program_exercise_target_reps_min_over_max_is_rejected(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id)))
    await db_session.flush()
    program_day = (
        await db_session.execute(select(ProgramDay).where(ProgramDay.program_id == program.id))
    ).scalar_one()
    db_session.add(
        ProgramExercise(
            **_program_exercise_kwargs(
                program_day.id, exercise_id, target_reps_min=12, target_reps_max=8
            )
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_program_exercise_target_reps_max_over_ceiling_is_rejected(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id)))
    await db_session.flush()
    program_day = (
        await db_session.execute(select(ProgramDay).where(ProgramDay.program_id == program.id))
    ).scalar_one()
    db_session.add(
        ProgramExercise(**_program_exercise_kwargs(program_day.id, exercise_id, target_reps_max=31))
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_program_exercise_rest_seconds_out_of_range_is_rejected(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id)))
    await db_session.flush()
    program_day = (
        await db_session.execute(select(ProgramDay).where(ProgramDay.program_id == program.id))
    ).scalar_one()
    db_session.add(
        ProgramExercise(**_program_exercise_kwargs(program_day.id, exercise_id, rest_seconds=301))
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_program_exercises_position_must_be_unique_within_day(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id)))
    await db_session.flush()
    program_day = (
        await db_session.execute(select(ProgramDay).where(ProgramDay.program_id == program.id))
    ).scalar_one()
    db_session.add(ProgramExercise(**_program_exercise_kwargs(program_day.id, exercise_id)))
    await db_session.flush()
    db_session.add(ProgramExercise(**_program_exercise_kwargs(program_day.id, exercise_id)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_workout_session_unknown_status_is_rejected(db_session: AsyncSession) -> None:
    user = await _insert_user_with_profile(db_session)
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id, status="paused")))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_only_one_in_progress_session_per_user_is_enforced(
    db_session: AsyncSession,
) -> None:
    """§4.6, verbatim: ux_one_active_session (P2-ADR-03)."""
    user = await _insert_user_with_profile(db_session)
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_second_session_is_allowed_once_the_first_is_no_longer_in_progress(
    db_session: AsyncSession,
) -> None:
    user = await _insert_user_with_profile(db_session)
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id, status="completed")))
    await db_session.flush()
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()  # must not raise


async def test_deleting_program_day_sets_workout_session_program_day_id_null(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    """§4.6: program_day_id is ON DELETE SET NULL, not CASCADE -- deleting an old program
    must never delete the sessions logged against its days."""
    user = await _insert_user_with_profile(db_session)
    db_session.add(Program(**_program_kwargs(user.id)))
    await db_session.flush()
    program = (
        await db_session.execute(select(Program).where(Program.user_id == user.id))
    ).scalar_one()
    db_session.add(ProgramDay(**_program_day_kwargs(program.id)))
    await db_session.flush()
    program_day = (
        await db_session.execute(select(ProgramDay).where(ProgramDay.program_id == program.id))
    ).scalar_one()
    db_session.add(
        WorkoutSession(**_workout_session_kwargs(user.id, program_day_id=program_day.id))
    )
    await db_session.flush()
    session_row = (
        await db_session.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    ).scalar_one()
    await db_session.commit()
    user_id = user.id
    session_id = session_row.id
    program_day_id = program_day.id

    # See test_deleting_program_cascades_to_days_and_exercises for why app.user_id must
    # be bound: program_days is FORCE ROW LEVEL SECURITY and its owner-EXISTS policy
    # would otherwise make this DELETE match zero rows.
    engine = create_async_engine(migrator_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
            )
            await conn.execute(
                text("DELETE FROM program_days WHERE id = :did"), {"did": program_day_id}
            )
    finally:
        await engine.dispose()

    db_session.expire_all()
    await set_rls_user(db_session, str(user_id))
    refreshed = await db_session.get(WorkoutSession, session_id)
    assert refreshed is not None
    assert refreshed.program_day_id is None


async def test_workout_set_reps_out_of_range_is_rejected(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()
    session_row = (
        await db_session.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    ).scalar_one()
    db_session.add(WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id, reps=101)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_workout_set_weight_out_of_range_is_rejected(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()
    session_row = (
        await db_session.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    ).scalar_one()
    db_session.add(WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id, weight_kg=501)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_workout_set_rpe_out_of_range_is_rejected(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()
    session_row = (
        await db_session.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    ).scalar_one()
    db_session.add(WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id, rpe=4)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_workout_set_rpe_may_be_absent(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    """§4.7: rpe is optional -- 'a user who does not know what RPE is never sees the
    field' (§8.4). Must not raise."""
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()
    session_row = (
        await db_session.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    ).scalar_one()
    db_session.add(WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id)))
    await db_session.flush()  # must not raise


async def test_workout_sets_set_index_must_be_unique_per_session_and_exercise(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()
    session_row = (
        await db_session.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    ).scalar_one()
    db_session.add(WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id, set_index=1)))
    await db_session.flush()
    db_session.add(WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id, set_index=1)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deleting_workout_session_cascades_to_its_sets(
    db_session: AsyncSession, migrator_database_url: str
) -> None:
    user = await _insert_user_with_profile(db_session)
    exercise_id = await _insert_exercise(migrator_database_url)
    await set_rls_user(db_session, str(user.id))
    db_session.add(WorkoutSession(**_workout_session_kwargs(user.id)))
    await db_session.flush()
    session_row = (
        await db_session.execute(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    ).scalar_one()
    db_session.add(WorkoutSet(**_workout_set_kwargs(session_row.id, exercise_id)))
    await db_session.flush()
    await db_session.commit()
    user_id = user.id
    session_id = session_row.id

    # See test_deleting_program_cascades_to_days_and_exercises for why app.user_id must
    # be bound: workout_sessions is FORCE ROW LEVEL SECURITY, so this DELETE would
    # otherwise match zero rows and the cascade below would never actually be exercised.
    engine = create_async_engine(migrator_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
            )
            await conn.execute(
                text("DELETE FROM workout_sessions WHERE id = :sid"), {"sid": session_id}
            )
    finally:
        await engine.dispose()

    # No re-bind needed: the assertion is that zero rows come back, true whether RLS
    # hides them or they are genuinely gone -- unlike the SET NULL test above, this one
    # never needs to read a row back as its owner.
    db_session.expire_all()
    assert (
        await db_session.execute(select(WorkoutSet).where(WorkoutSet.session_id == session_id))
    ).first() is None


async def test_body_weight_out_of_range_is_rejected(db_session: AsyncSession) -> None:
    user = await _insert_user_with_profile(db_session)
    db_session.add(BodyWeightEntry(**_body_weight_kwargs(user.id, weight_kg=301)))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_body_weight_entry_must_be_unique_per_user_and_day(
    db_session: AsyncSession,
) -> None:
    user = await _insert_user_with_profile(db_session)
    measured_on = date.today()
    db_session.add(BodyWeightEntry(**_body_weight_kwargs(user.id, measured_on=measured_on)))
    await db_session.flush()
    db_session.add(BodyWeightEntry(**_body_weight_kwargs(user.id, measured_on=measured_on)))
    with pytest.raises(IntegrityError):
        await db_session.flush()
