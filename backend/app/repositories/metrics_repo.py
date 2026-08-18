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
from decimal import Decimal

from sqlalchemy import ColumnElement, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

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
# T-21 (§5.11 GET /records, §5.12 GET /dashboard, P2-ADR-05/07), rewritten by T-22c
# (P2-NFR-01): each function below is a SQL-side aggregate returning at most one row
# per exercise the user has ever performed, instead of a full row-per-set scan handed
# to Python. §5.11's three per-exercise records are independent aggregates -- heaviest
# weight, best e1RM, best session volume -- so they are three focused queries here
# rather than one query trying to answer all three at once; dashboard_service.py zips
# their results together by exercise_id.
#
# Every ORDER BY below ends in the same (local_date ASC, <logged_at-ish> ASC) tie
# break. That is not a stylistic default: it reproduces exactly what the pre-T-22c
# Python implementation did by scanning `rows` pre-sorted ascending by (local_date,
# logged_at) and only replacing its running "best" on a *strict* improvement --
# Python's own max()/`value > best` idiom keeps the first-encountered maximum, i.e.
# the earliest one. `DISTINCT ON (exercise_id)` after that same ORDER BY keeps the
# identical row PostgreSQL, not Python, breaks the tie.
# =========================================================================================


def _half_up_e1rm(
    weight_kg: InstrumentedAttribute[Decimal], reps: InstrumentedAttribute[int]
) -> ColumnElement[float | Decimal]:
    """SQL-side twin of `services.metrics.estimate_one_rep_max`: the same Epley
    formula (P2-ADR-04) rounded the same way -- ROUND_HALF_UP, quantized to 2dp --
    so a row this module picks as an exercise's best e1RM is provably the row that
    function would also call the winner, not merely a numerically close one.
    `floor(x*100 + 0.5)/100` rather than SQL's built-in `round(numeric, int)`:
    `weight_kg` is always >= 0 (`CHECK BETWEEN 0 AND 500`), so half-away-from-zero
    and half-up coincide, and `floor`'s rounding direction is exact and
    version-independent -- this does not lean on `round()`'s tie-breaking mode
    happening to match Python's `Decimal` `ROUND_HALF_UP`.
    """
    return func.floor(weight_kg * (30 + reps) / 30 * 100 + Decimal("0.5")) / 100


def _completed_non_warmup_conditions(
    user_id: uuid.UUID,
    exercise_ids: Sequence[uuid.UUID] | None,
    before: tuple[date, datetime] | None,
) -> list[ColumnElement[bool]]:
    """The one WHERE clause every query below shares: completed sessions only,
    warm-ups excluded (P2-ADR-04), explicit `user_id` filter as defence in depth on
    top of RLS (this module's own precedent, see
    `completed_non_warmup_sets_for_exercise` above). `exercise_ids=None` means every
    exercise -- §5.11's unfiltered GET /records and the dashboard's always-unfiltered
    `recent_records`; a given sequence narrows to those exercises only -- GET
    /records' own `exercise_id` filter, or `max_e1rm_by_exercise`'s baseline lookup
    scoped to one session's own exercises. `before`, when given, adds T-26b's
    `records_set` window: strictly preceding a (local_date, started_at) pair, via a
    row-wise `tuple_` comparison -- only `max_e1rm_by_exercise` below ever passes it.
    """
    conditions: list[ColumnElement[bool]] = [
        WorkoutSession.user_id == user_id,
        WorkoutSession.status == "completed",
        WorkoutSet.is_warmup.is_(False),
    ]
    if exercise_ids is not None:
        conditions.append(WorkoutSet.exercise_id.in_(exercise_ids))
    if before is not None:
        before_local_date, before_started_at = before
        conditions.append(
            tuple_(WorkoutSession.local_date, WorkoutSession.started_at)
            < (before_local_date, before_started_at)
        )
    return conditions


async def best_weight_set_per_exercise(
    session: AsyncSession, user_id: uuid.UUID, *, exercise_ids: Sequence[uuid.UUID] | None = None
) -> list[tuple[Exercise, WorkoutSet, date]]:
    """§5.11 `heaviest_set`. `DISTINCT ON (exercise_id)` after `ORDER BY weight_kg
    DESC, local_date ASC, logged_at ASC` returns exactly the row the old
    `max(pairs, key=lambda pair: pair[0].weight_kg)` picked -- see this section's own
    header note on why that tie-break direction matters. The only one of this
    module's aggregates that also joins `Exercise`: every exercise_id the other two
    below can return is already a subset of this one's (identical WHERE clause), so
    callers zip on `exercise_id` against this query's rows rather than joining
    `Exercise` three times over for the same ~60-row result.
    """
    conditions = _completed_non_warmup_conditions(user_id, exercise_ids, None)
    stmt = (
        select(Exercise, WorkoutSet, WorkoutSession.local_date)
        .select_from(WorkoutSet)
        .join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
        .join(Exercise, Exercise.id == WorkoutSet.exercise_id)
        .where(*conditions)
        .order_by(
            WorkoutSet.exercise_id,
            WorkoutSet.weight_kg.desc(),
            WorkoutSession.local_date.asc(),
            WorkoutSet.logged_at.asc(),
        )
        .distinct(WorkoutSet.exercise_id)
    )
    result = await session.execute(stmt)
    return [
        (exercise, workout_set, local_date) for exercise, workout_set, local_date in result.all()
    ]


async def best_e1rm_set_per_exercise(
    session: AsyncSession, user_id: uuid.UUID, *, exercise_ids: Sequence[uuid.UUID] | None = None
) -> list[tuple[uuid.UUID, WorkoutSet, date]]:
    """§5.11 `best_e1rm`. Same `DISTINCT ON` shape as `best_weight_set_per_exercise`,
    ranked by `_half_up_e1rm` instead of `weight_kg` -- the row returned is the exact
    row the old per-set Python loop (`value > best_e1rm_value`, strict, over sets
    pre-sorted ascending by (local_date, logged_at)) would have kept, so
    `services.metrics.estimate_one_rep_max` applied to it afterward reproduces the
    identical displayed value bit-for-bit. Leading column is a plain `exercise_id`,
    not `Exercise` -- see `best_weight_set_per_exercise`'s own docstring for why only
    one of these three queries needs the join.
    """
    e1rm = _half_up_e1rm(WorkoutSet.weight_kg, WorkoutSet.reps)
    conditions = _completed_non_warmup_conditions(user_id, exercise_ids, None)
    stmt = (
        select(WorkoutSet.exercise_id, WorkoutSet, WorkoutSession.local_date)
        .select_from(WorkoutSet)
        .join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
        .where(*conditions)
        .order_by(
            WorkoutSet.exercise_id,
            e1rm.desc(),
            WorkoutSession.local_date.asc(),
            WorkoutSet.logged_at.asc(),
        )
        .distinct(WorkoutSet.exercise_id)
    )
    result = await session.execute(stmt)
    return [
        (exercise_id, workout_set, local_date)
        for exercise_id, workout_set, local_date in result.all()
    ]


async def best_session_volume_per_exercise(
    session: AsyncSession, user_id: uuid.UUID, *, exercise_ids: Sequence[uuid.UUID] | None = None
) -> list[tuple[uuid.UUID, Decimal, uuid.UUID, date, int]]:
    """§5.11 `best_session_volume` and `total_sets`, as one query. `per_session` sums
    this exercise's own non-warmup volume within each session -- P2-ADR-04's
    `set_volume_kg` summed, exactly `services.metrics.session_volume_kg`'s own
    arithmetic, restated as a SQL `SUM` because both sides are exact `Numeric`
    arithmetic, never float. The outer `DISTINCT ON` then keeps each exercise's best
    session, tied to the earliest (`local_date`, that session's own first set's
    `logged_at`) exactly as the old `max(volume_by_session_id, key=...)` over an
    insertion-ordered dict did (this section's own header note). `total_sets` rides
    along as a window `SUM` over the same per-session rows, so this one query answers
    both fields `_build_exercise_records` used to compute in two separate loops.
    """
    conditions = _completed_non_warmup_conditions(user_id, exercise_ids, None)
    per_session = (
        select(
            WorkoutSet.exercise_id.label("exercise_id"),
            WorkoutSet.session_id.label("session_id"),
            WorkoutSession.local_date.label("local_date"),
            func.sum(WorkoutSet.weight_kg * WorkoutSet.reps).label("session_volume_kg"),
            func.min(WorkoutSet.logged_at).label("first_logged_at"),
            func.count().label("set_count"),
        )
        .select_from(WorkoutSet)
        .join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
        .where(*conditions)
        .group_by(WorkoutSet.exercise_id, WorkoutSet.session_id, WorkoutSession.local_date)
        .subquery()
    )
    stmt = (
        select(
            per_session.c.exercise_id,
            per_session.c.session_volume_kg,
            per_session.c.session_id,
            per_session.c.local_date,
            func.sum(per_session.c.set_count).over(partition_by=per_session.c.exercise_id),
        )
        .order_by(
            per_session.c.exercise_id,
            per_session.c.session_volume_kg.desc(),
            per_session.c.local_date.asc(),
            per_session.c.first_logged_at.asc(),
        )
        .distinct(per_session.c.exercise_id)
    )
    result = await session.execute(stmt)
    return [
        (exercise_id, Decimal(volume_kg), session_id, local_date, int(total_sets))
        for exercise_id, volume_kg, session_id, local_date, total_sets in result.all()
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
# Rewritten by T-22c to share this module's SQL-side aggregation (P2-NFR-01) rather
# than a second unoptimised full-history scan.
# =========================================================================================


async def max_e1rm_by_exercise(
    session: AsyncSession,
    user_id: uuid.UUID,
    exercise_ids: Sequence[uuid.UUID],
    *,
    local_date: date,
    started_at: datetime,
) -> dict[uuid.UUID, Decimal]:
    """§5.8's `records_set` baseline: "a record is a set in THIS session whose e1RM
    beats the user's best from completed sessions that came BEFORE this one. Not
    'before now'." This is deliberately a different query from
    `completed_non_warmup_sets_for_exercise` above: that one excludes only the
    caller's own session and is correct for T-19's live `is_record`, where "this
    session" is necessarily the most recent completed one there can be (P2-ADR-03
    allows only one `in_progress` session at a time, so nothing later can have
    finished yet). Once a session is read back after later sessions exist -- which is
    exactly what GET /workouts/{id} does -- "all other completed sessions" and
    "completed sessions before this one" stop agreeing: the former would let a later,
    heavier session erase a record this session actually set at the time. Both POST
    .../finish and GET /workouts/{id} call this same function for that reason, so
    they can never disagree about what a given session's own `records_set` was.

    Unlike `best_e1rm_set_per_exercise`, no row is ever displayed for this baseline
    -- `workout_service._records_set_for_session` only ever compares it with `>`
    against the target session's own best -- so a plain `GROUP BY`/`MAX` aggregate
    is enough; there is no tie to break because nothing here identifies a winning
    row, only a winning value. `_half_up_e1rm` still matters: the comparison this
    feeds uses the same rounded value on both sides, exactly as the pre-existing
    code compared two already-rounded `services.metrics.estimate_one_rep_max` outputs.

    `exercise_ids` narrows the aggregate to only the exercises the target session
    itself logged -- the only ones a caller ever needs a baseline for -- rather than
    every exercise the user has ever performed. An empty sequence short-circuits to
    no query, matching `get_most_recent_completed_session_for_days`'s own precedent
    for an always-empty `IN ()`.
    """
    if not exercise_ids:
        return {}
    e1rm = _half_up_e1rm(WorkoutSet.weight_kg, WorkoutSet.reps)
    conditions = _completed_non_warmup_conditions(user_id, exercise_ids, (local_date, started_at))
    stmt = (
        select(WorkoutSet.exercise_id, func.max(e1rm))
        .select_from(WorkoutSet)
        .join(WorkoutSession, WorkoutSession.id == WorkoutSet.session_id)
        .where(*conditions)
        .group_by(WorkoutSet.exercise_id)
    )
    result = await session.execute(stmt)
    return {exercise_id: Decimal(value) for exercise_id, value in result.all()}
