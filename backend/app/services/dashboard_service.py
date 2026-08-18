"""Business logic for spec §5.11 (GET /records) and §5.12 (GET /dashboard),
P2-FR-011/012, P2-ADR-05/07. No HTTP objects here (§3) -- the router passes plain
values and gets a plain dataclass back, matching workout_service.py's/
program_service.py's own convention.

Both endpoints live in one module because T-21 names them together: P2-ADR-05's
read-time records aggregation is also what feeds the dashboard's own `recent_records`
block, and the dashboard is the "one endpoint, computed server-side" P2-ADR-07
describes -- there is no separate records_service.py for T-21 to split this into (see
this task's own file list).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.body_weight import BodyWeightEntry
from app.models.exercise import Exercise
from app.models.profile import Profile
from app.models.program import Program, ProgramDay
from app.models.user import User
from app.models.workout import WorkoutSession, WorkoutSet
from app.repositories import body_weight_repo, metrics_repo, program_repo, workout_repo
from app.services import metrics

_MINOR_AGE = 18
_WEIGHT_WINDOW_DAYS = 30
_RECENT_RECORDS_LIMIT = 5
_DISCLAIMER_KEY = "common.medicalDisclaimer"


def _today_local(timezone_name: str) -> date:
    """Same now-then-astimezone-then-date shape workout_service.start_session and
    body_weight_service._today_local already use for §4.2's "today" (not imported
    from either -- neither is a dependency of this module, matching those modules'
    own precedent of a private copy over a cross-service import)."""
    return datetime.now(UTC).astimezone(ZoneInfo(timezone_name)).date()


def compute_age(birth_date: date, *, today: date) -> int:
    """Same computation as profile_service.compute_age/program_service.compute_age
    (§4.3: "age is computed from birth_date, never stored"). Reimplemented rather than
    imported, matching program_service.compute_age's own documented reasoning: neither
    module is a dependency of this one."""
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


# =========================================================================================
# §5.11 GET /records, P2-ADR-05
# =========================================================================================


@dataclass(frozen=True)
class ExerciseRecord:
    exercise: Exercise
    heaviest_set: WorkoutSet
    heaviest_set_local_date: date
    best_e1rm_set: WorkoutSet
    best_e1rm_value_kg: Decimal
    best_e1rm_local_date: date
    best_session_volume_kg: Decimal
    best_session_volume_session_id: uuid.UUID
    best_session_volume_local_date: date
    total_sets: int


async def _fetch_exercise_records(
    session: AsyncSession, user_id: uuid.UUID, *, exercise_ids: Sequence[uuid.UUID] | None
) -> list[ExerciseRecord]:
    """§5.11's three per-exercise records (P2-ADR-05), now three SQL-side aggregates
    (P2-NFR-01, metrics_repo.py's own T-22c header note) instead of a full row-per-set
    scan grouped in Python: each of the three repository calls below returns at most
    one row per exercise the user has ever performed non-warmup work on in a
    completed session, so this only zips three small result sets together by
    `exercise_id` -- it never loops over an individual set. Exercises never performed
    are simply absent from `best_weight_set_per_exercise`'s rows, so they never
    produce an entry -- §5.11: "omitted entirely rather than returned with nulls."

    `best_e1rm_value_kg` is recomputed here via `metrics.estimate_one_rep_max` on the
    single winning row `best_e1rm_set_per_exercise` already identified, rather than
    trusting any rounding done in SQL for ranking purposes -- the displayed value is
    byte-identical to what the pre-T-22c per-set Python loop produced, because it is
    the same pure function applied to the same winning (weight_kg, reps) pair.
    """
    weight_rows = await metrics_repo.best_weight_set_per_exercise(
        session, user_id, exercise_ids=exercise_ids
    )
    if not weight_rows:
        return []

    e1rm_rows = await metrics_repo.best_e1rm_set_per_exercise(
        session, user_id, exercise_ids=exercise_ids
    )
    volume_rows = await metrics_repo.best_session_volume_per_exercise(
        session, user_id, exercise_ids=exercise_ids
    )

    e1rm_by_exercise: dict[uuid.UUID, tuple[WorkoutSet, date]] = {
        exercise_id: (workout_set, local_date) for exercise_id, workout_set, local_date in e1rm_rows
    }
    volume_by_exercise: dict[uuid.UUID, tuple[Decimal, uuid.UUID, date]] = {}
    total_sets_by_exercise: dict[uuid.UUID, int] = {}
    for exercise_id, volume_kg, volume_session_id, volume_local_date, total_sets in volume_rows:
        volume_by_exercise[exercise_id] = (volume_kg, volume_session_id, volume_local_date)
        total_sets_by_exercise[exercise_id] = total_sets

    records: list[ExerciseRecord] = []
    for exercise, heaviest_set, heaviest_local_date in weight_rows:
        best_e1rm_set, best_e1rm_local_date = e1rm_by_exercise[exercise.id]
        best_volume_kg, best_volume_session_id, best_volume_local_date = volume_by_exercise[
            exercise.id
        ]
        records.append(
            ExerciseRecord(
                exercise=exercise,
                heaviest_set=heaviest_set,
                heaviest_set_local_date=heaviest_local_date,
                best_e1rm_set=best_e1rm_set,
                best_e1rm_value_kg=metrics.estimate_one_rep_max(
                    best_e1rm_set.weight_kg, best_e1rm_set.reps
                ),
                best_e1rm_local_date=best_e1rm_local_date,
                best_session_volume_kg=best_volume_kg,
                best_session_volume_session_id=best_volume_session_id,
                best_session_volume_local_date=best_volume_local_date,
                total_sets=total_sets_by_exercise[exercise.id],
            )
        )

    records.sort(key=lambda record: record.exercise.slug)
    return records


async def get_records(
    session: AsyncSession, user: User, *, exercise_id: uuid.UUID | None
) -> list[ExerciseRecord]:
    """§5.11. `exercise_id=None` reaches `_fetch_exercise_records` as `exercise_ids=
    None` -- every exercise, unfiltered -- exactly like the dashboard's own call
    below; a given id narrows to that one exercise only.
    """
    exercise_ids = [exercise_id] if exercise_id is not None else None
    return await _fetch_exercise_records(session, user.id, exercise_ids=exercise_ids)


# =========================================================================================
# §5.12 GET /dashboard, P2-ADR-07
# =========================================================================================


@dataclass(frozen=True)
class NextWorkoutInfo:
    program_day_id: uuid.UUID
    day_index: int
    label_key: str
    exercise_count: int
    estimated_minutes: int


@dataclass(frozen=True)
class ThisWeekInfo:
    completed: int
    target: int
    local_week_start: date


@dataclass(frozen=True)
class DashboardResult:
    greeting_name: str
    active_session: WorkoutSession | None
    next_workout: NextWorkoutInfo | None
    streak: metrics.StreakResult
    this_week: ThisWeekInfo
    weight: dict[str, Any]
    recent_records: list[ExerciseRecord]
    program_stale: dict[str, str] | None
    disclaimer_key: str


def _stale_reason(program: Program, profile: Profile) -> dict[str, str] | None:
    """Same comparison as program_service._stale_reason (§5.4/§4.3: "goal" and
    "experience_level" are the snapshotted fields the dashboard compares against the
    live profile). Reimplemented rather than imported: that function is private
    (module-local) to program_service.py, matching this module's own `compute_age`/
    `_resolved_name` precedent of a private copy over reaching into another service's
    internals.
    """
    if program.goal != profile.goal:
        return {"reason": "goal_changed", "from": program.goal, "to": profile.goal}
    if program.experience_level != profile.experience_level:
        return {
            "reason": "experience_level_changed",
            "from": program.experience_level,
            "to": profile.experience_level,
        }
    return None


async def _get_next_workout(
    session: AsyncSession, user: User, days: list[ProgramDay]
) -> NextWorkoutInfo | None:
    """§5.12 `next_workout`: "The day after the most recently completed one, wrapping
    at days_per_week." `days` is always non-empty here (the generator never creates a
    program with zero days) -- the caller only reaches this once a current program is
    known to exist.
    """
    day_ids = [day.id for day in days]
    most_recent = await metrics_repo.get_most_recent_completed_session_for_days(
        session, user.id, day_ids
    )

    days_by_index = {day.day_index: day for day in days}
    ordered_indices = sorted(days_by_index)

    current_index = None
    if most_recent is not None:
        current_day = next((d for d in days if d.id == most_recent.program_day_id), None)
        current_index = current_day.day_index if current_day is not None else None

    if current_index is not None and current_index in ordered_indices:
        position = ordered_indices.index(current_index)
        next_index = ordered_indices[(position + 1) % len(ordered_indices)]
    else:
        # Never trained against this program yet (or the most recent completed
        # session's day was not one of it -- an empty session with no program_day_id):
        # the day after "none" is the first day.
        next_index = ordered_indices[0]

    next_day = days_by_index[next_index]
    exercise_rows = await program_repo.list_day_exercises_with_exercise(session, next_day.id)
    estimated_minutes = metrics.estimated_session_minutes(
        metrics.ProgramDayLoadInput(target_sets=pe.target_sets, rest_seconds=pe.rest_seconds)
        for pe, _ in exercise_rows
    )
    return NextWorkoutInfo(
        program_day_id=next_day.id,
        day_index=next_day.day_index,
        label_key=next_day.label_key,
        exercise_count=len(exercise_rows),
        estimated_minutes=estimated_minutes,
    )


def _build_weight_block(
    entries: list[BodyWeightEntry], *, include_change_key: bool
) -> dict[str, Any]:
    """§5.12 `weight`. Sourced from `body_weight_entries` alone, never
    `profiles.weight_kg` -- the block's own `measured_on`/`sparkline` fields need a
    logged date, and onboarding (§5.8) sets `profiles.weight_kg` without writing a log
    entry (only PUT /body-weight and PATCH /profile do, per P2-ADR-06's two named
    writers), so a profile-only weight has no date to report here.

    P2-SAF-002: `include_change_key` controls whether `change_30d_kg` -- the one key
    §6.5 names as "framing that implies a target direction" -- appears in the returned
    dict at all. This task's own requirement is to *omit* the key for a minor, not
    merely null it out, so this returns a plain dict (schemas/metrics.py's `weight`
    field is typed `dict[str, Any]` for exactly this reason) rather than a fixed
    pydantic model, which would always serialise every declared field.
    """
    latest = entries[-1] if entries else None
    first = entries[0] if entries else None
    block: dict[str, Any] = {
        "latest_kg": float(latest.weight_kg) if latest is not None else None,
        "measured_on": latest.measured_on.isoformat() if latest is not None else None,
        "sparkline": [
            {"measured_on": entry.measured_on.isoformat(), "weight_kg": float(entry.weight_kg)}
            for entry in entries
        ],
    }
    if include_change_key:
        block["change_30d_kg"] = (
            float(latest.weight_kg - first.weight_kg)
            if latest is not None and first is not None
            else None
        )
    return block


async def get_dashboard(session: AsyncSession, user: User, profile: Profile) -> DashboardResult:
    """§5.12: "Everything the home screen renders, in one round trip." A brand-new
    account (no program, no sessions, no weight entries) falls through every branch
    below to its own null/zero default -- never a 404 (this task's own requirement).
    """
    today_local = _today_local(profile.timezone)
    age = compute_age(profile.birth_date, today=today_local)
    is_minor = age < _MINOR_AGE

    active_session = await workout_repo.get_active_session(session, user.id)

    program = await program_repo.get_current_program(session, user.id)
    next_workout: NextWorkoutInfo | None = None
    program_stale: dict[str, str] | None = None
    days_per_week = 0
    if program is not None:
        days = await program_repo.list_program_days(session, program.id)
        next_workout = await _get_next_workout(session, user, days)
        program_stale = _stale_reason(program, profile)
        days_per_week = program.days_per_week

    local_dates = await metrics_repo.list_completed_session_local_dates(session, user.id)
    streak = metrics.compute_streak(local_dates, today=today_local)

    week_start = today_local - timedelta(days=today_local.weekday())  # Monday, ISO 8601
    completed_this_week = await metrics_repo.count_completed_sessions_in_range(
        session, user.id, date_from=week_start, date_to=today_local
    )
    this_week = ThisWeekInfo(
        completed=completed_this_week, target=days_per_week, local_week_start=week_start
    )

    weight_window_start = today_local - timedelta(days=_WEIGHT_WINDOW_DAYS - 1)
    weight_entries = await body_weight_repo.list_in_range(
        session, user.id, date_from=weight_window_start, date_to=today_local
    )
    weight = _build_weight_block(weight_entries, include_change_key=not is_minor)

    exercise_records = await _fetch_exercise_records(session, user.id, exercise_ids=None)
    recent_records = sorted(
        exercise_records, key=lambda record: record.best_e1rm_local_date, reverse=True
    )[:_RECENT_RECORDS_LIMIT]

    return DashboardResult(
        greeting_name=profile.name,
        active_session=active_session,
        next_workout=next_workout,
        streak=streak,
        this_week=this_week,
        weight=weight,
        recent_records=recent_records,
        program_stale=program_stale,
        disclaimer_key=_DISCLAIMER_KEY,
    )
