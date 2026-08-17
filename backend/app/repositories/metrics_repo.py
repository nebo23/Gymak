"""spec P2-ADR-05: personal records are a read-time aggregation over `workout_sets`,
never stored. This module holds those queries; the arithmetic (e1RM, volume) stays in
`services/metrics.py`, which takes no dependency on `models/` or a database session.

T-19 is the first consumer: POST/PATCH `.../sets`' `is_record` needs the user's best
e1RM for an exercise from *before* the set being evaluated, computed fresh every time
(P2-ADR-04). T-21's GET /records and the dashboard aggregation extend this module --
they do not replace this query.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.workout import WorkoutSession, WorkoutSet


async def completed_non_warmup_sets_for_exercise(
    session: AsyncSession,
    user_id: uuid.UUID,
    exercise_id: uuid.UUID,
    *,
    exclude_session_id: uuid.UUID,
) -> list[WorkoutSet]:
    """§5.7's `is_record`: "the user's history excluding this session's other sets."
    §5.8/P2-ADR-04: an abandoned session's sets are excluded from records, so this
    reads only `status = 'completed'` sessions -- `exclude_session_id` on top of that
    is what §5.7 names explicitly. It is never redundant with the status filter: the
    caller's own session is always `in_progress` while its sets are being logged (a
    closed session rejects new/edited sets with 409 SESSION_NOT_ACTIVE before this is
    ever reached), so the completed-only filter alone already keeps it out -- this is
    the belt to that braces, and the literal mechanism §5.7's wording names. Warm-up
    sets are excluded (P2-ADR-04): they can never set a record.

    Explicit `user_id` filter, defence in depth on top of RLS -- the same pattern
    every other query in this codebase's repositories follows (§3).
    """
    result = await session.execute(
        select(WorkoutSet)
        .join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.status == "completed",
            WorkoutSession.id != exclude_session_id,
            WorkoutSet.exercise_id == exercise_id,
            WorkoutSet.is_warmup.is_(False),
        )
    )
    return list(result.scalars().all())


# =========================================================================================
# T-21: GET /records (§5.11) and the GET /dashboard aggregate (§5.12), P2-ADR-05/07.
# =========================================================================================


async def list_completed_non_warmup_sets(
    session: AsyncSession, user_id: uuid.UUID, *, exercise_id: uuid.UUID | None = None
) -> list[tuple[WorkoutSet, WorkoutSession, Exercise]]:
    """§5.11: "Records are a read-time aggregation ... Warm-up sets and non-completed
    sessions are excluded everywhere." The single query both GET /records (optionally
    filtered to one exercise) and the dashboard's `recent_records` (always unfiltered)
    build their aggregates from -- exercises the caller has never performed simply
    never appear, since there is no row for them to join against (§5.11: "omitted
    entirely rather than returned with nulls"). Ordered by (session local_date, set
    logged_at) ascending so ties in weight/e1RM/volume resolve to the earliest-set
    instance deterministically, rather than to whatever order Postgres happens to
    return rows in.
    """
    stmt = (
        select(WorkoutSet, WorkoutSession, Exercise)
        .join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
        .join(Exercise, Exercise.id == WorkoutSet.exercise_id)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.status == "completed",
            WorkoutSet.is_warmup.is_(False),
        )
        .order_by(WorkoutSession.local_date.asc(), WorkoutSet.logged_at.asc())
    )
    if exercise_id is not None:
        stmt = stmt.where(WorkoutSet.exercise_id == exercise_id)
    result = await session.execute(stmt)
    return [
        (workout_set, workout_session, exercise)
        for workout_set, workout_session, exercise in result.all()
    ]


async def list_completed_session_local_dates(
    session: AsyncSession, user_id: uuid.UUID
) -> list[date]:
    """§5.12 `streak`: the distinct set of calendar days that have at least one
    completed session, in whatever timezone each session's own `local_date` (§4.6) was
    already resolved through at write time -- fed straight into
    `services.metrics.compute_streak`, which does the rest as pure `date` arithmetic.
    """
    result = await session.execute(
        select(WorkoutSession.local_date)
        .where(WorkoutSession.user_id == user_id, WorkoutSession.status == "completed")
        .distinct()
    )
    return list(result.scalars().all())


async def count_completed_sessions_in_range(
    session: AsyncSession, user_id: uuid.UUID, *, date_from: date, date_to: date
) -> int:
    """§5.12 `this_week.completed`: completed sessions whose `local_date` falls within
    the caller's own local week, inclusive of both ends."""
    result = await session.execute(
        select(func.count(WorkoutSession.id)).where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.status == "completed",
            WorkoutSession.local_date >= date_from,
            WorkoutSession.local_date <= date_to,
        )
    )
    return result.scalar_one()


async def get_most_recent_completed_session_for_days(
    session: AsyncSession, user_id: uuid.UUID, program_day_ids: Sequence[uuid.UUID]
) -> WorkoutSession | None:
    """§5.12 `next_workout`: "the day after the most recently completed one." Scoped to
    `program_day_ids` -- the *current* program's own days -- so a session logged
    against a superseded program (§4.3: old programs are kept, never deleted) can never
    be mistaken for progress against a plan the user has since regenerated; its
    `day_index` need not even mean the same thing under a different `days_per_week`.
    An empty `program_day_ids` short-circuits to `None` rather than an always-false
    `IN ()` query.
    """
    if not program_day_ids:
        return None
    result = await session.execute(
        select(WorkoutSession)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.status == "completed",
            WorkoutSession.program_day_id.in_(program_day_ids),
        )
        .order_by(WorkoutSession.local_date.desc(), WorkoutSession.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# =========================================================================================
# T-26b: `records_set` for POST .../finish and GET /workouts/{id} (§5.8/5.9, P2-ADR-04/05).
# =========================================================================================


async def list_completed_non_warmup_sets_before(
    session: AsyncSession,
    user_id: uuid.UUID,
    exercise_ids: Sequence[uuid.UUID],
    *,
    local_date: date,
    started_at: datetime,
) -> list[WorkoutSet]:
    """§5.8's `records_set`: "a record is a set in THIS session whose e1RM beats the
    user's best from completed sessions that came BEFORE this one. Not 'before now'."
    Ordered by (`local_date`, `started_at`) via a row-wise `tuple_` comparison, so a
    same-day tie still resolves correctly. This is deliberately a different query from
    `completed_non_warmup_sets_for_exercise` above: that one excludes only the caller's
    own session and is correct for T-19's live `is_record`, where "this session" is
    necessarily the most recent completed one there can be (P2-ADR-03 allows only one
    `in_progress` session at a time, so nothing later can have finished yet). Once a
    session is read back after later sessions exist -- which is exactly what
    GET /workouts/{id} does -- "all other completed sessions" and "completed sessions
    before this one" stop agreeing: the former would let a later, heavier session erase
    a record this session actually set at the time. Both POST .../finish and
    GET /workouts/{id} call this same query for that reason, so they can never disagree
    about what a given session's own `records_set` was.

    `exercise_ids` narrows the join to only the exercises the target session itself
    logged -- the only ones a caller ever needs a baseline for -- rather than every
    exercise the user has ever performed. An empty sequence short-circuits to no query,
    matching `get_most_recent_completed_session_for_days`'s own precedent for an
    always-empty `IN ()`.
    """
    if not exercise_ids:
        return []
    result = await session.execute(
        select(WorkoutSet)
        .join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.status == "completed",
            WorkoutSet.exercise_id.in_(exercise_ids),
            WorkoutSet.is_warmup.is_(False),
            tuple_(WorkoutSession.local_date, WorkoutSession.started_at) < (local_date, started_at),
        )
    )
    return list(result.scalars().all())
