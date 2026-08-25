"""Business logic for spec §5.6 (POST /workouts, GET /workouts/active) and §5.8
(POST /workouts/{id}/finish, POST /workouts/{id}/abandon), P2-FR-005/007, P2-ADR-03.
No HTTP objects here (§3) -- the router passes plain values and gets a plain
dataclass/model back, matching program_service.py's convention.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ExerciseNotFoundError, NotFoundError, ValidationError
from app.models.exercise import Exercise
from app.models.profile import Profile
from app.models.user import User
from app.models.workout import WorkoutSession, WorkoutSet
from app.repositories import exercise_repo, metrics_repo, workout_repo
from app.schemas.workout import WorkoutSetPatchRequest
from app.services import metrics

# --- error codes new to this task (spec §7.2) ---------------------------------------------
#
# Subclassed here rather than in core/errors.py, which this task's file list does not
# include -- the same pattern program_service.py (T-17) already set for
# PROGRAM_NOT_FOUND/SESSION_ACTIVE_BLOCKS_REGENERATION/PLAN_GENERATION_FAILED.


class SessionAlreadyActiveError(AppError):
    code = "SESSION_ALREADY_ACTIVE"
    status = 409
    title = "A workout session is already in progress"


class SessionNotActiveError(AppError):
    code = "SESSION_NOT_ACTIVE"
    status = 409
    title = "This session is no longer active"


class SessionNotFoundError(AppError):
    code = "SESSION_NOT_FOUND"
    status = 404
    title = "Unknown session"


class EmptySessionError(AppError):
    code = "EMPTY_SESSION"
    status = 422
    title = "This session has no logged sets"


class SetNotFoundError(AppError):
    code = "SET_NOT_FOUND"
    status = 404
    title = "Unknown set"


# =========================================================================================
# §7.1 field validation for §5.7 (T-19). Same `_field_error` shape as
# profile_service.py's own validators; not imported from there since that module is not
# one of this task's files.
# =========================================================================================

_MIN_REPS = 1
_MAX_REPS = 100
_MIN_SET_WEIGHT_KG = Decimal("0")
_MAX_SET_WEIGHT_KG = Decimal("500")
_MIN_RPE = Decimal("5")
_MAX_RPE = Decimal("10")
_RPE_STEP = Decimal("0.5")


def _field_error(field: str, code: str, detail: str) -> ValidationError:
    return ValidationError(detail=detail, errors=[{"field": field, "code": code}])


def validate_reps(value: int) -> int:
    """§7.1: "reps: integer 1-100." """
    if not (_MIN_REPS <= value <= _MAX_REPS):
        raise _field_error("reps", "OUT_OF_RANGE", "reps must be between 1 and 100.")
    return value


def validate_set_weight_kg(value: Decimal) -> Decimal:
    """§7.1: "weight_kg (set): 0-500, two decimals." Two-decimal precision is the
    column's own Numeric(6,2) (§4.7) -- not re-validated here, matching
    profile_service.validate_height_cm/weight_kg's own precedent of checking range
    only and trusting the column to round."""
    if not (_MIN_SET_WEIGHT_KG <= value <= _MAX_SET_WEIGHT_KG):
        raise _field_error("weight_kg", "OUT_OF_RANGE", "weight_kg must be between 0 and 500.")
    return value


def validate_rpe(value: Decimal) -> Decimal:
    """§7.1: "rpe: 5-10 in steps of 0.5, or absent." """
    in_range = _MIN_RPE <= value <= _MAX_RPE
    on_step = (value - _MIN_RPE) % _RPE_STEP == 0
    if not (in_range and on_step):
        raise _field_error("rpe", "OUT_OF_RANGE", "rpe must be between 5 and 10, in steps of 0.5.")
    return value


async def start_session(
    session: AsyncSession, user: User, profile: Profile, program_day_id: uuid.UUID | None
) -> WorkoutSession:
    """§5.6/P2-ADR-03. `local_date` is `started_at` resolved into the caller's §4.2
    timezone -- both derived from the same `now` read below, so there is no risk of
    the stored `started_at` and the stored `local_date` disagreeing about which
    instant they describe.

    The active-session check runs before the insert as the friendly 409 path;
    §4.6's `ux_one_active_session` partial unique index is what actually guarantees
    at-most-one under a race between two concurrent starts (P2-ADR-03's own framing:
    "in the database, not the service").
    """
    if program_day_id is not None:
        day = await workout_repo.get_program_day_for_user(session, program_day_id, user.id)
        if day is None:
            raise NotFoundError(detail="Unknown program day.")

    active = await workout_repo.get_active_session(session, user.id)
    if active is not None:
        # §5.6: "409 SESSION_ALREADY_ACTIVE ... with detail carrying the active
        # session's id" -- the spec names the `detail` field itself as the carrier.
        raise SessionAlreadyActiveError(detail=str(active.id))

    now = datetime.now(UTC)
    local_date = now.astimezone(ZoneInfo(profile.timezone)).date()

    workout_session = await workout_repo.create_session(
        session, user.id, program_day_id=program_day_id, started_at=now, local_date=local_date
    )
    await session.commit()
    return workout_session


async def get_active_session(session: AsyncSession, user: User) -> WorkoutSession | None:
    """§5.1: "GET /workouts/active ... the in-progress session, or 204." """
    return await workout_repo.get_active_session(session, user.id)


@dataclass(frozen=True)
class ClosedSessionResult:
    session: WorkoutSession
    set_count: int
    exercise_count: int


@dataclass(frozen=True)
class RecordSetEntry:
    """§5.8's `records_set` array element. `kind` is always `"e1rm"` -- the same single
    kind T-19's in-session `is_record` already uses (see `SetRecord` above); nothing
    else in this codebase computes a different kind of record."""

    exercise_id: uuid.UUID
    kind: str
    value: Decimal


@dataclass(frozen=True)
class FinishSessionResult:
    session: WorkoutSession
    set_count: int
    exercise_count: int
    records_set: list[RecordSetEntry]


async def _get_owned_session(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> WorkoutSession:
    workout_session = await workout_repo.get_session(session, session_id, user_id)
    if workout_session is None:
        raise SessionNotFoundError(detail="Unknown session.")
    return workout_session


def _assert_in_progress(workout_session: WorkoutSession) -> None:
    """P2-ADR-03: "in_progress -> completed | abandoned. No other transitions."
    Applies identically to a finish and an abandon attempt on an already-closed
    session -- §5.8 states the 409 explicitly for abandon and implies it for finish
    by the same state-machine rule §7.2's SESSION_NOT_ACTIVE row covers generically
    ("Writing to, finishing, or abandoning a closed session")."""
    if workout_session.status != "in_progress":
        raise SessionNotActiveError(detail="This session has already been finished or abandoned.")


async def finish_session(
    session: AsyncSession, user: User, session_id: uuid.UUID, notes: str | None
) -> FinishSessionResult:
    """§5.8. `422 EMPTY_SESSION` on zero sets, before any computation -- "recording a
    completed workout with nothing in it corrupts the streak." Duration and volume
    are computed from the sets already in the database (T-18's own note: sets are
    seeded directly in tests until T-19 adds POST /workouts/{id}/sets)."""
    workout_session = await _get_owned_session(session, session_id, user.id)
    _assert_in_progress(workout_session)

    sets = await workout_repo.list_sets(session, workout_session.id)
    if not sets:
        raise EmptySessionError(
            detail="Finish requires at least one logged set; consider abandoning instead."
        )

    last_logged_at = max(one_set.logged_at for one_set in sets)
    duration_seconds = metrics.session_duration_seconds(workout_session.started_at, last_logged_at)
    total_volume_kg = metrics.session_volume_kg(
        metrics.SetMetricInput(
            weight_kg=one_set.weight_kg, reps=one_set.reps, is_warmup=one_set.is_warmup
        )
        for one_set in sets
    )
    exercise_count = len({one_set.exercise_id for one_set in sets})

    updated = await workout_repo.mark_finished(
        session,
        workout_session,
        ended_at=datetime.now(UTC),
        duration_seconds=duration_seconds,
        total_volume_kg=total_volume_kg,
        notes=notes,
    )
    records_set = await _records_set_for_session(session, updated, sets)
    await session.commit()
    return FinishSessionResult(
        session=updated,
        set_count=len(sets),
        exercise_count=exercise_count,
        records_set=records_set,
    )


# =========================================================================================
# T-26b: `records_set`, shared by `finish_session` above and `get_session_detail` below
# (§5.8/5.9, P2-ADR-04/05). See metrics_repo.list_completed_non_warmup_sets_before's own
# docstring for why this must compare against completed sessions strictly *before* the
# target session, never "all other completed sessions" -- the latter is only safe at the
# instant a session finishes (P2-ADR-03: nothing later can have completed yet), and silently
# wrong for a GET /workouts/{id} read back after later sessions exist.
# =========================================================================================


def _best_e1rm_by_exercise(sets: Iterable[WorkoutSet]) -> dict[uuid.UUID, Decimal]:
    """The target session's own best e1RM per exercise, from its in-memory
    `session_sets` (§4.7/P2-ADR-04: warm-ups never contribute). Iteration order is
    preserved in the returned dict's key order, so calling this on a session's own
    sets in logged order gives deterministic first-appearance ordering for free, with
    no separate sort. The history/baseline side of this same comparison is no longer
    built by calling this a second time (T-22c, P2-NFR-01) -- see
    `metrics_repo.max_e1rm_by_exercise`, a SQL-side aggregate over history instead.
    """
    best: dict[uuid.UUID, Decimal] = {}
    for workout_set in sets:
        if workout_set.is_warmup:
            continue
        value = _e1rm_for(workout_set)
        current = best.get(workout_set.exercise_id)
        if current is None or value > current:
            best[workout_set.exercise_id] = value
    return best


async def _records_set_for_session(
    session: AsyncSession, workout_session: WorkoutSession, session_sets: Sequence[WorkoutSet]
) -> list[RecordSetEntry]:
    """At most one entry per exercise: the target session's own best e1RM for it, when
    that beats the user's best from completed sessions strictly before this one.
    Mirrors `_new_set_record`'s qualification rule (warm-ups never qualify, and no
    prior baseline means no record -- an exercise's first-ever outing cannot announce
    one here either) but aggregates per exercise across the whole session rather than
    per set, so a ramp-up of progressively heavier sets reports the session's single
    best once, not once per set that happened to beat the baseline.

    Gated on `status == "completed"`: an abandoned or still-`in_progress` session was
    never officially finished, matching the asymmetry the schema already draws between
    `WorkoutFinishResponse` (carries `records_set`) and `WorkoutAbandonResponse` (does
    not) -- a session you walked away from should not tell you it set a record.
    """
    if workout_session.status != "completed":
        return []

    session_best = _best_e1rm_by_exercise(session_sets)
    if not session_best:
        return []

    baseline_by_exercise = await metrics_repo.max_e1rm_by_exercise(
        session,
        workout_session.user_id,
        list(session_best),
        local_date=workout_session.local_date,
        started_at=workout_session.started_at,
    )

    records: list[RecordSetEntry] = []
    for exercise_id, value in session_best.items():
        baseline = baseline_by_exercise.get(exercise_id)
        if baseline is not None and value > baseline:
            records.append(RecordSetEntry(exercise_id=exercise_id, kind="e1rm", value=value))
    return records


async def abandon_session(
    session: AsyncSession, user: User, session_id: uuid.UUID
) -> ClosedSessionResult:
    """§5.8: "abandon keeps sets, computes nothing." set_count/exercise_count in the
    response are plain counts of what is already in the database, not a derived
    metric -- duration_seconds/total_volume_kg are the two things left uncomputed.
    """
    workout_session = await _get_owned_session(session, session_id, user.id)
    _assert_in_progress(workout_session)

    sets = await workout_repo.list_sets(session, workout_session.id)
    updated = await workout_repo.mark_abandoned(
        session, workout_session, ended_at=datetime.now(UTC)
    )
    await session.commit()
    return ClosedSessionResult(
        session=updated,
        set_count=len(sets),
        exercise_count=len({one_set.exercise_id for one_set in sets}),
    )


# =========================================================================================
# §5.7 POST/PATCH/DELETE /workouts/{id}/sets/{set_id} (T-19)
# =========================================================================================


@dataclass(frozen=True)
class SetDerivedValues:
    volume_kg: Decimal
    e1rm_kg: Decimal


@dataclass(frozen=True)
class SessionTotals:
    set_count: int
    volume_kg: Decimal


@dataclass(frozen=True)
class SetRecord:
    kind: str
    previous: Decimal


@dataclass(frozen=True)
class SetActionResult:
    workout_set: WorkoutSet
    derived: SetDerivedValues
    totals: SessionTotals
    record: SetRecord | None


async def _get_owned_session_for_update(
    session: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> WorkoutSession:
    """`create_set`'s own variant of `_get_owned_session`: holds the row locked
    (`workout_repo.get_session_for_update`) for the rest of this transaction, so a
    second, concurrent POST for the same session cannot compute `next_set_index` from
    a stale MAX(set_index) -- see that repo function's docstring. Never used by
    PATCH/DELETE, which do not allocate a new index."""
    workout_session = await workout_repo.get_session_for_update(session, session_id, user_id)
    if workout_session is None:
        raise SessionNotFoundError(detail="Unknown session.")
    return workout_session


def _e1rm_for(workout_set: WorkoutSet) -> Decimal:
    return metrics.estimate_one_rep_max(workout_set.weight_kg, workout_set.reps)


def _new_set_record(
    *, target: WorkoutSet, baseline: Decimal | None, other_session_sets: Iterable[WorkoutSet]
) -> SetRecord | None:
    """§5.7's `is_record`, e1RM only (the kind its own worked example shows). `target`
    is a new e1RM record when it beats `baseline` -- the user's best e1RM for this
    exercise from *completed* sessions other than this one (`metrics_repo.py`) -- and
    no *other* set already logged in this same session has already beaten `baseline`
    too. That second condition is this task's own "done when": a ramp-up of
    progressively heavier sets in one session announces the record once, comparing
    every set against the same fixed `baseline` rather than against each other, so it
    is not re-announced on every heavier set that follows the one that first broke it.
    """
    if target.is_warmup or baseline is None:
        return None
    if _e1rm_for(target) <= baseline:
        return None
    already_claimed = any(
        not other.is_warmup
        and other.exercise_id == target.exercise_id
        and other.id != target.id
        and _e1rm_for(other) > baseline
        for other in other_session_sets
    )
    if already_claimed:
        return None
    return SetRecord(kind="e1rm", previous=baseline)


async def _build_set_action_result(
    session: AsyncSession, workout_session: WorkoutSession, target: WorkoutSet
) -> SetActionResult:
    """Shared by `create_set`/`update_set`: `derived`, `session_totals` and
    `is_record` are always computed fresh (P2-ADR-04: never stored), identically
    whichever endpoint produced `target` (already flushed by the caller).
    """
    session_sets = await workout_repo.list_sets(session, workout_session.id)
    totals = SessionTotals(
        set_count=len(session_sets),
        volume_kg=metrics.session_volume_kg(
            metrics.SetMetricInput(weight_kg=s.weight_kg, reps=s.reps, is_warmup=s.is_warmup)
            for s in session_sets
        ),
    )

    history = await metrics_repo.completed_non_warmup_sets_for_exercise(
        session, workout_session.user_id, target.exercise_id, exclude_session_id=workout_session.id
    )
    baseline = max((_e1rm_for(s) for s in history), default=None)
    record = _new_set_record(target=target, baseline=baseline, other_session_sets=session_sets)

    derived = SetDerivedValues(
        volume_kg=metrics.set_volume_kg(target.weight_kg, target.reps), e1rm_kg=_e1rm_for(target)
    )
    return SetActionResult(workout_set=target, derived=derived, totals=totals, record=record)


async def create_set(
    session: AsyncSession,
    user: User,
    session_id: uuid.UUID,
    *,
    exercise_id: uuid.UUID,
    reps: int,
    weight_kg: Decimal,
    rpe: Decimal | None,
    is_warmup: bool,
) -> SetActionResult:
    """§5.7 POST. `set_index` is assigned server-side, the next integer for
    (session, exercise) -- never accepted from the client."""
    workout_session = await _get_owned_session_for_update(session, session_id, user.id)
    _assert_in_progress(workout_session)

    # `user.id` scopes this to the seeded library plus the caller's OWN custom rows
    # (migration a1c9f2e4b703). Another user's custom exercise resolves to None here and
    # so becomes the same generic "Unknown exercise id." 404 as one that never existed --
    # which is what stops a guessed uuid being logged against. The FK alone would not:
    # Postgres runs foreign-key checks as the referencing table's owner, bypassing RLS.
    exercise = await exercise_repo.get_by_id(session, user.id, exercise_id)
    if exercise is None:
        raise ExerciseNotFoundError(detail="Unknown exercise id.")

    validated_reps = validate_reps(reps)
    validated_weight_kg = validate_set_weight_kg(weight_kg)
    validated_rpe = validate_rpe(rpe) if rpe is not None else None

    next_index = await workout_repo.next_set_index(session, workout_session.id, exercise_id)
    new_set = await workout_repo.create_set(
        session,
        session_id=workout_session.id,
        exercise_id=exercise_id,
        set_index=next_index,
        reps=validated_reps,
        weight_kg=validated_weight_kg,
        rpe=validated_rpe,
        is_warmup=is_warmup,
    )
    result = await _build_set_action_result(session, workout_session, new_set)
    await session.commit()
    return result


async def update_set(
    session: AsyncSession,
    user: User,
    session_id: uuid.UUID,
    set_id: uuid.UUID,
    body: WorkoutSetPatchRequest,
) -> SetActionResult:
    """§5.7 PATCH: "Any of reps, weight_kg, rpe, is_warmup. Not exercise_id" (the
    schema itself has no such field -- see schemas/workout.py). `exclude_unset=True`
    is what lets `rpe: null` (clear it) mean something different from omitting `rpe`
    entirely (leave it), matching profile_service.update_profile's own convention.
    """
    workout_session = await _get_owned_session(session, session_id, user.id)
    _assert_in_progress(workout_session)

    target = await workout_repo.get_set(session, set_id, workout_session.id)
    if target is None:
        raise SetNotFoundError(detail="Unknown set.")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationError(detail="The request body must include at least one field to update.")

    updates: dict[str, object] = {}
    if "reps" in changes:
        reps = changes["reps"]
        if reps is None:
            raise _field_error("reps", "OUT_OF_RANGE", "reps must be between 1 and 100.")
        updates["reps"] = validate_reps(reps)
    if "weight_kg" in changes:
        weight_kg = changes["weight_kg"]
        if weight_kg is None:
            raise _field_error("weight_kg", "OUT_OF_RANGE", "weight_kg must be between 0 and 500.")
        updates["weight_kg"] = validate_set_weight_kg(weight_kg)
    if "rpe" in changes:
        rpe = changes["rpe"]
        updates["rpe"] = validate_rpe(rpe) if rpe is not None else None
    if "is_warmup" in changes:
        is_warmup = changes["is_warmup"]
        if is_warmup is None:
            raise _field_error("is_warmup", "INVALID", "is_warmup must be a boolean.")
        updates["is_warmup"] = is_warmup

    updated = await workout_repo.update_set(session, target, **updates)
    result = await _build_set_action_result(session, workout_session, updated)
    await session.commit()
    return result


async def delete_set(
    session: AsyncSession, user: User, session_id: uuid.UUID, set_id: uuid.UUID
) -> None:
    """§5.7 DELETE: "204. Remaining sets are not re-indexed." """
    workout_session = await _get_owned_session(session, session_id, user.id)
    _assert_in_progress(workout_session)

    target = await workout_repo.get_set(session, set_id, workout_session.id)
    if target is None:
        raise SetNotFoundError(detail="Unknown set.")

    await workout_repo.delete_set(session, target)
    await session.commit()


# =========================================================================================
# §5.9 GET /workouts (history) and GET /workouts/{id} (one session in full), P2-FR-008
# =========================================================================================

_SESSION_STATUSES = ("in_progress", "completed", "abandoned")


def validate_status_filter(value: str) -> str:
    """§5.9's "status filter". §7.1 names no row for it, so this follows
    `exercise_repo.decode_cursor`'s own precedent for the other §5-level filter the
    spec describes without a dedicated code: VALIDATION_ERROR with `<field>:INVALID`.
    Rejecting an unknown status rather than returning an empty page is deliberate --
    a typo'd filter that silently yields "no workouts" reads to the caller exactly
    like a user who has never trained.
    """
    if value not in _SESSION_STATUSES:
        raise _field_error(
            "status",
            "INVALID",
            "status must be one of: " + ", ".join(_SESSION_STATUSES) + ".",
        )
    return value


@dataclass(frozen=True)
class HistoryItem:
    """One row of §5.9's history page -- a summary, never the sets themselves."""

    session: WorkoutSession
    label_key: str | None
    set_count: int


@dataclass(frozen=True)
class HistoryPage:
    items: list[HistoryItem]
    next_cursor: str | None


async def list_history(
    session: AsyncSession,
    user: User,
    *,
    date_from: date | None,
    date_to: date | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> HistoryPage:
    """§5.9: "History is cursor-paginated, newest first, and returns summaries only."

    Every status is included by default, `in_progress` among them: the history is the
    log of what the user did, and an abandoned or still-open session is part of that
    record even though P2-ADR-04 keeps both out of records and the streak. Narrowing
    is what the `status` filter is for.
    """
    validated_status = validate_status_filter(status) if status is not None else None

    rows, next_cursor = await workout_repo.list_sessions(
        session,
        user.id,
        date_from=date_from,
        date_to=date_to,
        status=validated_status,
        limit=limit,
        cursor=cursor,
    )
    set_counts = await workout_repo.count_sets_by_session(
        session, [workout_session.id for workout_session, _ in rows]
    )
    return HistoryPage(
        items=[
            HistoryItem(
                session=workout_session,
                label_key=day.label_key if day is not None else None,
                set_count=set_counts.get(workout_session.id, 0),
            )
            for workout_session, day in rows
        ],
        next_cursor=next_cursor,
    )


@dataclass(frozen=True)
class SessionDetailSet:
    workout_set: WorkoutSet
    derived: SetDerivedValues


@dataclass(frozen=True)
class SessionDetailExercise:
    exercise: Exercise
    sets: list[SessionDetailSet]


@dataclass(frozen=True)
class SessionDetail:
    session: WorkoutSession
    label_key: str | None
    exercises: list[SessionDetailExercise]
    set_count: int
    exercise_count: int
    records_set: list[RecordSetEntry]


async def get_session_detail(
    session: AsyncSession, user: User, session_id: uuid.UUID
) -> SessionDetail:
    """§5.9: "returns the session with every set, grouped by exercise in `position`
    order for a plan-backed session and in first-logged order for an empty one, each
    set carrying its `derived` block."

    "Empty one" is read as "a session with no program day behind it" -- a session with
    no *sets* has no exercises to order at all, so the sentence only says something
    about the plan-backed/ad-hoc distinction. An exercise the user swapped in, absent
    from the plan's own day, has no `position` and sorts after every exercise that has
    one, keeping first-logged order among themselves.

    `derived` is recomputed here, never read from storage (P2-ADR-04): the same
    `metrics` functions the live logging path uses, so a set reads back with exactly
    the numbers it was logged with.
    """
    row = await workout_repo.get_session_with_day(session, session_id, user.id)
    if row is None:
        raise SessionNotFoundError(detail="Unknown session.")
    workout_session, day = row

    positions: dict[uuid.UUID, int] = {}
    if workout_session.program_day_id is not None:
        positions = await workout_repo.list_day_exercise_positions(
            session, workout_session.program_day_id
        )

    rows = await workout_repo.list_sets_with_exercise(session, workout_session.id)

    # Grouped in first-logged order: `rows` is already ordered by logged_at, so the
    # first time an exercise appears fixes its place, and a plan `position` (when there
    # is one) reorders the groups afterwards.
    grouped: dict[uuid.UUID, list[SessionDetailSet]] = {}
    exercises_by_id: dict[uuid.UUID, Exercise] = {}
    for workout_set, exercise in rows:
        exercises_by_id.setdefault(exercise.id, exercise)
        grouped.setdefault(exercise.id, []).append(
            SessionDetailSet(
                workout_set=workout_set,
                derived=SetDerivedValues(
                    volume_kg=metrics.set_volume_kg(workout_set.weight_kg, workout_set.reps),
                    e1rm_kg=metrics.estimate_one_rep_max(workout_set.weight_kg, workout_set.reps),
                ),
            )
        )

    first_logged_order = list(grouped)
    ordered_exercise_ids = sorted(
        first_logged_order,
        # An exercise with no plan position sorts after every one that has a position
        # (len(positions) is strictly greater than any real position index within this
        # day), and ties -- including every exercise in an ad-hoc session, where the
        # dict is empty -- fall back to first-logged order.
        key=lambda exercise_id: (
            positions.get(exercise_id, len(positions) + first_logged_order.index(exercise_id) + 1),
            first_logged_order.index(exercise_id),
        ),
    )

    records_set = await _records_set_for_session(
        session, workout_session, [workout_set for workout_set, _ in rows]
    )

    return SessionDetail(
        session=workout_session,
        label_key=day.label_key if day is not None else None,
        exercises=[
            SessionDetailExercise(exercise=exercises_by_id[exercise_id], sets=grouped[exercise_id])
            for exercise_id in ordered_exercise_ids
        ],
        set_count=len(rows),
        exercise_count=len(grouped),
        records_set=records_set,
    )
