"""Workout session data access (spec §4.6-4.7, §5.6, §5.8, P2-ADR-03). §3:
repositories are the only place a query is written, and every function here takes
`user_id` explicitly, matching every other repository in this codebase.

One query reaches outside `workout_sessions`/`workout_sets`: `get_program_day_for_user`
(against `program_days`/`programs`), needed to validate a caller-supplied
`program_day_id` belongs to the caller (§5.6) before a session is started against it.
`program_repo.py` already writes its own narrow, single-purpose query against
`workout_sessions` for its regeneration-blocking check (`has_active_session`) rather
than depending on a `workout_repo.py` that did not exist when T-17 was written --
that module's own docstring says as much. The same reasoning applies here in reverse:
this module writes its own query against `program_days`/`programs` rather than
reaching into `program_repo.py`.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Uuid

from app.core.errors import ValidationError
from app.models.exercise import Exercise
from app.models.program import Program, ProgramDay, ProgramExercise
from app.models.workout import WorkoutSession, WorkoutSet


async def get_program_day_for_user(
    session: AsyncSession, program_day_id: uuid.UUID, user_id: uuid.UUID
) -> ProgramDay | None:
    """§5.6: "404 NOT_FOUND if the program_day_id belongs to another user's
    program." Explicit `user_id` filter, defence in depth on top of
    `program_days`'/`programs`' own RLS policies (P2-ADR-09) -- the same parent-join
    shape those policies themselves use.
    """
    result = await session.execute(
        select(ProgramDay)
        .join(Program, Program.id == ProgramDay.program_id)
        .where(ProgramDay.id == program_day_id, Program.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_active_session(session: AsyncSession, user_id: uuid.UUID) -> WorkoutSession | None:
    """P2-ADR-03: the caller's `in_progress` session, if any -- GET /workouts/active
    (§5.1) and the friendly pre-check ahead of §4.6's `ux_one_active_session` index,
    which is the actual guarantee under a race."""
    result = await session.execute(
        select(WorkoutSession).where(
            WorkoutSession.user_id == user_id, WorkoutSession.status == "in_progress"
        )
    )
    return result.scalar_one_or_none()


async def get_session(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> WorkoutSession | None:
    """§7.2 SESSION_NOT_FOUND: "Unknown session, or another user's -- generic."
    Explicit `user_id` filter means both cases resolve to the same `None` here."""
    result = await session.execute(
        select(WorkoutSession).where(
            WorkoutSession.id == session_id, WorkoutSession.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def get_session_for_update(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> WorkoutSession | None:
    """Same ownership scoping as `get_session`, but with `FOR UPDATE`: T-19's
    `create_set` holds this lock for the rest of its transaction so a second,
    concurrent POST for the same session cannot read `next_set_index`'s MAX(set_index)
    before it changes underneath it -- see that function's own docstring for why a
    lock, not a retry, is what closes the race here. PATCH/DELETE never allocate a new
    index, so neither needs this -- `get_session` is enough for them.
    """
    result = await session.execute(
        select(WorkoutSession)
        .where(WorkoutSession.id == session_id, WorkoutSession.user_id == user_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def create_session(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    program_day_id: uuid.UUID | None,
    started_at: datetime,
    local_date: date,
) -> WorkoutSession:
    """§5.6/§4.6. `started_at` is passed explicitly (the server clock, read once in
    workout_service) rather than left to the column's `server_default=func.now()`,
    so it is the exact same instant `local_date` was resolved from -- the default
    stays as the schema-level guarantee for any future writer, but this path never
    relies on a second, independent clock read disagreeing with the first.
    """
    workout_session = WorkoutSession(
        user_id=user_id,
        program_day_id=program_day_id,
        status="in_progress",
        started_at=started_at,
        local_date=local_date,
    )
    session.add(workout_session)
    await session.flush()
    return workout_session


async def list_sets(session: AsyncSession, session_id: uuid.UUID) -> list[WorkoutSet]:
    """§5.8: what finish needs to compute duration/volume/counts. §5.7 (T-19): also
    what `create_set`/`update_set` re-read after their own mutation to recompute
    `session_totals` and `is_record` fresh (P2-ADR-04). No `user_id` filter:
    `workout_sets` carries none of its own (P2-ADR-09), ownership already proven by
    the caller's prior `get_session`/`get_session_for_update` lookup.
    """
    result = await session.execute(select(WorkoutSet).where(WorkoutSet.session_id == session_id))
    return list(result.scalars().all())


async def mark_finished(
    session: AsyncSession,
    workout_session: WorkoutSession,
    *,
    ended_at: datetime,
    duration_seconds: int,
    total_volume_kg: Decimal,
    notes: str | None,
) -> WorkoutSession:
    """§5.8. Mutates the row the caller already fetched (via `get_session`) rather
    than re-querying -- matching `program_repo.supersede_current_program`'s own
    fetch-then-mutate shape, minus the redundant second fetch since the caller here
    already holds the row for its own state check."""
    workout_session.status = "completed"
    workout_session.ended_at = ended_at
    workout_session.duration_seconds = duration_seconds
    workout_session.total_volume_kg = total_volume_kg
    workout_session.notes = notes
    await session.flush()
    return workout_session


async def mark_abandoned(
    session: AsyncSession, workout_session: WorkoutSession, *, ended_at: datetime
) -> WorkoutSession:
    """§5.8: "abandon sets status = 'abandoned', ended_at, and computes nothing."
    duration_seconds/total_volume_kg are left untouched (NULL, as they always are
    for a session that never finished)."""
    workout_session.status = "abandoned"
    workout_session.ended_at = ended_at
    await session.flush()
    return workout_session


async def next_set_index(
    session: AsyncSession, session_id: uuid.UUID, exercise_id: uuid.UUID
) -> int:
    """§5.7: "the next integer for that exercise within that session." MAX(set_index)
    + 1, not COUNT(*) + 1: DELETE never re-indexes (§5.7), so a session left with sets
    1 and 3 (2 deleted) must produce 4 next, not 3 -- COUNT would collide with
    `uq_workout_sets_session_exercise_index`. Concurrent callers for the same session
    are serialized by `get_session_for_update`'s lock in the caller, not by a retry
    here -- this function only ever runs with that lock already held.
    """
    result = await session.execute(
        select(func.max(WorkoutSet.set_index)).where(
            WorkoutSet.session_id == session_id, WorkoutSet.exercise_id == exercise_id
        )
    )
    current_max = result.scalar_one_or_none()
    return 1 if current_max is None else current_max + 1


async def get_set(
    session: AsyncSession, set_id: uuid.UUID, session_id: uuid.UUID
) -> WorkoutSet | None:
    """§7.2 SET_NOT_FOUND: "Unknown set, or not in this session" -- both collapse to
    the same `None` here via the explicit `session_id` filter, the same generic-404
    shape `get_session`'s own docstring uses for SESSION_NOT_FOUND."""
    result = await session.execute(
        select(WorkoutSet).where(WorkoutSet.id == set_id, WorkoutSet.session_id == session_id)
    )
    return result.scalar_one_or_none()


async def create_set(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    exercise_id: uuid.UUID,
    set_index: int,
    reps: int,
    weight_kg: Decimal,
    rpe: Decimal | None,
    is_warmup: bool,
) -> WorkoutSet:
    workout_set = WorkoutSet(
        session_id=session_id,
        exercise_id=exercise_id,
        set_index=set_index,
        reps=reps,
        weight_kg=weight_kg,
        rpe=rpe,
        is_warmup=is_warmup,
    )
    session.add(workout_set)
    await session.flush()
    return workout_set


async def update_set(session: AsyncSession, workout_set: WorkoutSet, **fields: Any) -> WorkoutSet:
    """§5.7 PATCH: apply only the fields the caller passed. Mutates the row the
    caller already fetched (via `get_set`) rather than re-querying, matching
    `profile_repo.update_profile`'s own `**fields` shape and `mark_finished`'s own
    fetch-then-mutate one."""
    for column, value in fields.items():
        setattr(workout_set, column, value)
    await session.flush()
    return workout_set


async def delete_set(session: AsyncSession, workout_set: WorkoutSet) -> None:
    """§5.7 DELETE: "204. Remaining sets are not re-indexed" -- a plain delete, no
    renumbering of any other row."""
    await session.delete(workout_set)
    await session.flush()


# =========================================================================================
# §5.9 GET /workouts (history) and GET /workouts/{id} (one session in full), P2-FR-008.
# =========================================================================================

# (local_date, started_at, id) -- the full sort key, encoded into the opaque cursor below.
# `local_date` alone is not unique (two sessions in one day) and neither is it strictly
# monotonic with `started_at` once a user changes timezone (§4.2), so the tuple carries
# `started_at` to order within a day and `id` as the final, guaranteed-unique tie-break.
# Without that last component a keyset page boundary could repeat or skip a row.
_CURSOR_SEPARATOR = "|"


def encode_history_cursor(workout_session: WorkoutSession) -> str:
    """Opaque, base64-wrapped copy of the last row's sort key -- the same shape
    `exercise_repo.encode_cursor` uses for its own single-column key, widened to the
    three columns this ordering actually needs."""
    raw = _CURSOR_SEPARATOR.join(
        (
            workout_session.local_date.isoformat(),
            workout_session.started_at.isoformat(),
            str(workout_session.id),
        )
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_history_cursor(cursor: str) -> tuple[date, datetime, uuid.UUID]:
    """Mirrors `exercise_repo.decode_cursor`'s contract, including its error: a value
    this endpoint did not issue is a VALIDATION_ERROR on the `cursor` field, never a
    500 and never a silently ignored filter."""
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        local_date_raw, started_at_raw, id_raw = decoded.split(_CURSOR_SEPARATOR)
        return (
            date.fromisoformat(local_date_raw),
            datetime.fromisoformat(started_at_raw),
            uuid.UUID(id_raw),
        )
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(
            detail="cursor is not a value this endpoint issued.",
            errors=[{"field": "cursor", "code": "INVALID"}],
        ) from exc


async def list_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    date_from: date | None,
    date_to: date | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[tuple[WorkoutSession, ProgramDay | None]], str | None]:
    """§5.9: "History is cursor-paginated, newest first, and returns summaries only --
    id, local_date, status, duration, volume, set count, and the program day's
    label_key. Optional from / to date filters and a status filter."

    The `label_key` join is an OUTER join: `program_day_id` is nullable (§4.6 -- a
    session started without a plan) and `ON DELETE SET NULL` can null it after the
    fact, so an inner join would silently drop exactly the ad-hoc sessions the history
    exists to show. Set counts are not counted here -- `count_sets_by_session` below
    does that in one grouped query for the whole page, rather than one COUNT per row.

    Ordered `(local_date, started_at, id)` DESC, which `ix_sessions_user_local_date`
    (§4.9) leads on. Keyset pagination via a row-value comparison on that same tuple,
    so a page boundary never repeats or skips a row as sessions are added between
    calls -- the same guarantee `exercise_repo.list_active`'s single-column cursor
    gives, over a key that needs three columns to be unique.
    """
    stmt = (
        select(WorkoutSession, ProgramDay)
        .outerjoin(ProgramDay, ProgramDay.id == WorkoutSession.program_day_id)
        .where(WorkoutSession.user_id == user_id)
    )
    if date_from is not None:
        stmt = stmt.where(WorkoutSession.local_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(WorkoutSession.local_date <= date_to)
    if status is not None:
        stmt = stmt.where(WorkoutSession.status == status)
    if cursor:
        cursor_local_date, cursor_started_at, cursor_id = decode_history_cursor(cursor)
        stmt = stmt.where(
            tuple_(WorkoutSession.local_date, WorkoutSession.started_at, WorkoutSession.id)
            < tuple_(
                literal(cursor_local_date, Date),
                literal(cursor_started_at, DateTime(timezone=True)),
                literal(cursor_id, Uuid(as_uuid=True)),
            )
        )
    # One extra row fetched, never returned: its presence is what tells the caller a
    # next page exists, without a second COUNT-style query (exercise_repo's own trick).
    stmt = stmt.order_by(
        WorkoutSession.local_date.desc(),
        WorkoutSession.started_at.desc(),
        WorkoutSession.id.desc(),
    ).limit(limit + 1)

    rows = [(workout_session, day) for workout_session, day in (await session.execute(stmt)).all()]
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_history_cursor(rows[-1][0])
    return rows, next_cursor


async def count_sets_by_session(
    session: AsyncSession, session_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """§5.9's `set_count`, for a whole page of history in one grouped query -- the same
    shape `program_repo.count_exercises_by_day` uses for its own per-parent counts, and
    for the same reason (one query per page, not one per row). Warm-ups are counted:
    §5.9 says "set count", unqualified, and the detail view shows them too (P2-ADR-04
    excludes them from *records and volume*, not from existing).
    """
    if not session_ids:
        return {}
    result = await session.execute(
        select(WorkoutSet.session_id, func.count(WorkoutSet.id))
        .where(WorkoutSet.session_id.in_(session_ids))
        .group_by(WorkoutSet.session_id)
    )
    return {session_id: count for session_id, count in result.all()}


async def get_session_with_day(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[WorkoutSession, ProgramDay | None] | None:
    """`get_session`'s own ownership scoping, plus the program day the history detail
    needs for its `label_key`. Outer join for the same reason `list_sessions` uses one.
    """
    result = await session.execute(
        select(WorkoutSession, ProgramDay)
        .outerjoin(ProgramDay, ProgramDay.id == WorkoutSession.program_day_id)
        .where(WorkoutSession.id == session_id, WorkoutSession.user_id == user_id)
    )
    row = result.first()
    if row is None:
        return None
    workout_session, day = row
    return workout_session, day


async def list_sets_with_exercise(
    session: AsyncSession, session_id: uuid.UUID
) -> list[tuple[WorkoutSet, Exercise]]:
    """§5.9's detail view: every set in the session with the exercise it names, so the
    response can group by exercise without a second lookup per row. Ordered by
    `logged_at` then `set_index` -- "first-logged order" (§5.9) for a session with no
    plan behind it, and the within-exercise ordering for every session either way.
    `position` ordering for a plan-backed session is applied in the service, which is
    where `list_day_exercise_positions` below is joined in.

    No `user_id` filter: `workout_sets` carries none of its own (P2-ADR-09), ownership
    already proven by the caller's prior `get_session_with_day` lookup -- the same
    reasoning `list_sets` states.
    """
    result = await session.execute(
        select(WorkoutSet, Exercise)
        .join(Exercise, Exercise.id == WorkoutSet.exercise_id)
        .where(WorkoutSet.session_id == session_id)
        .order_by(WorkoutSet.logged_at.asc(), WorkoutSet.set_index.asc())
    )
    return [(workout_set, exercise) for workout_set, exercise in result.all()]


async def list_day_exercise_positions(
    session: AsyncSession, program_day_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    """§5.9: a plan-backed session's detail groups exercises "in position order" --
    the `program_exercises.position` of the day the session was started against (§4.5).
    Returned as a lookup rather than a list because the session may contain an exercise
    the plan never prescribed (the user swapped one in), which then has no position and
    sorts after everything the plan did name.
    """
    result = await session.execute(
        select(ProgramExercise.exercise_id, ProgramExercise.position).where(
            ProgramExercise.program_day_id == program_day_id
        )
    )
    return {exercise_id: position for exercise_id, position in result.all()}
