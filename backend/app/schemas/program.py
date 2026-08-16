"""Request/response shapes for spec §5.3 (POST /program/generate), §5.4 (GET /program)
and §5.5 (GET /program/days/{day_id}), P2-FR-002/003/004.

Following schemas/exercise.py and schemas/profile.py's convention: request bodies stay
plain and permissive (no pydantic validator that raises -- `days_per_week` range
checking happens in program_service, so a violation gets the §7.2 problem+json
envelope rather than FastAPI's default body), and a module-level `build_*` function
turns ORM rows plus whatever extra context a route needs (the caller's language, a
generated plan's transient notes) into the response model.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

from app.models.exercise import Exercise
from app.models.program import Program, ProgramDay, ProgramExercise
from app.models.workout import WorkoutSession, WorkoutSet

if TYPE_CHECKING:
    from collections.abc import Sequence

# Same convention as schemas/workout.py's/schemas/metrics.py's own DecimalAsFloat:
# Numeric columns parse into Decimal, but §5's wire format is a JSON number.
DecimalAsFloat = Annotated[
    Decimal, PlainSerializer(lambda value: float(value), return_type=float, when_used="json")
]


class ProgramGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_per_week: int


class ProgramDaySummary(BaseModel):
    """§5.3/§5.4: a day inside the program object -- summary only, `exercise_count`
    rather than the exercise list itself. `GET /program/days/{day_id}` (below) is where
    a day's full exercise list lives."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    day_index: int
    label_key: str
    focus_muscles: list[str]
    exercise_count: int
    # §5.12's own formula (services.metrics.estimated_session_minutes), computed over
    # this day's `target_sets`/`rest_seconds` -- T-24b (§5.4/§5.5): populated on every
    # day of both POST /program/generate and GET /program.
    estimated_minutes: int


class ProgramSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    days_per_week: int
    split_type: str
    goal: str
    experience_level: str
    generator_version: int
    created_at: datetime
    days: list[ProgramDaySummary]


class ProgramGenerateResponse(BaseModel):
    program: ProgramSummary
    # §6.2: "the response's notes_key explains why" (e.g. the beginner day cap). Not a
    # stored column -- `programs` carries no notes_key (spec §4.3) -- so this is only
    # ever populated on the generation response itself, never on a later GET /program
    # (see this task's report for why).
    notes_key: list[str]


class ProgramDayExerciseRef(BaseModel):
    """§5.5's nested `exercise` object -- deliberately narrower than
    schemas/exercise.py's ExerciseListItem; the spec's own example shows exactly these
    five fields and no more."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    equipment: str
    primary_muscle: str


class ProgramDayExerciseBestSet(BaseModel):
    """§5.5's `last_performance.best_set` -- reps and weight only, matching the spec's
    own worked example exactly."""

    reps: int
    weight_kg: DecimalAsFloat


class ProgramDayExerciseLastPerformance(BaseModel):
    """§5.5's `last_performance` -- the most recent COMPLETED session (P2-ADR-04)
    containing at least one non-warm-up set of this exercise. "Best" is not defined by
    the spec's own wording beyond showing the field; `program_service.
    _resolve_last_performance` is where that decision is made (highest e1RM, tie-broken
    on heavier weight_kg, then on earliest logged_at) -- this schema only carries the
    result of it."""

    session_id: uuid.UUID
    local_date: date
    best_set: ProgramDayExerciseBestSet


class ProgramDayExerciseDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    exercise: ProgramDayExerciseRef
    target_sets: int
    target_reps_min: int
    target_reps_max: int
    rest_seconds: int
    last_performance: ProgramDayExerciseLastPerformance | None


class ProgramDayDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    day_index: int
    label_key: str
    exercises: list[ProgramDayExerciseDetail]


class ProgramDayDetailResponse(BaseModel):
    day: ProgramDayDetail


class ProgramResponse(BaseModel):
    program: ProgramSummary
    # §5.4: "Includes a stale object when the profile has diverged ... null when they
    # agree." A plain dict rather than a nested model: its only two shapes are
    # {"reason", "from", "to"}, and "from" is a Python keyword-adjacent identifier that
    # would need a pydantic alias for no benefit over just building the dict directly.
    stale: dict[str, str] | None


def build_program_summary(
    program: Program,
    days: Sequence[ProgramDay],
    exercise_counts: dict[uuid.UUID, int],
    day_estimated_minutes: dict[uuid.UUID, int],
) -> ProgramSummary:
    return ProgramSummary(
        id=program.id,
        days_per_week=program.days_per_week,
        split_type=program.split_type,
        goal=program.goal,
        experience_level=program.experience_level,
        generator_version=program.generator_version,
        created_at=program.created_at,
        days=[
            ProgramDaySummary(
                id=day.id,
                day_index=day.day_index,
                label_key=day.label_key,
                focus_muscles=list(day.focus_muscles),
                exercise_count=exercise_counts.get(day.id, 0),
                estimated_minutes=day_estimated_minutes.get(day.id, 0),
            )
            for day in days
        ],
    )


def _build_last_performance(
    entry: tuple[WorkoutSession, WorkoutSet] | None,
) -> ProgramDayExerciseLastPerformance | None:
    if entry is None:
        return None
    workout_session, best_set = entry
    return ProgramDayExerciseLastPerformance(
        session_id=workout_session.id,
        local_date=workout_session.local_date,
        best_set=ProgramDayExerciseBestSet(reps=best_set.reps, weight_kg=best_set.weight_kg),
    )


def build_program_day_detail(
    day: ProgramDay,
    exercise_rows: Sequence[tuple[ProgramExercise, Exercise]],
    *,
    language: str,
    last_performance: dict[uuid.UUID, tuple[WorkoutSession, WorkoutSet]],
) -> ProgramDayDetail:
    return ProgramDayDetail(
        id=day.id,
        day_index=day.day_index,
        label_key=day.label_key,
        exercises=[
            ProgramDayExerciseDetail(
                id=program_exercise.id,
                position=program_exercise.position,
                exercise=ProgramDayExerciseRef(
                    id=exercise.id,
                    slug=exercise.slug,
                    name=exercise.name_ar if language == "ar" else exercise.name_en,
                    equipment=exercise.equipment,
                    primary_muscle=exercise.primary_muscle,
                ),
                target_sets=program_exercise.target_sets,
                target_reps_min=program_exercise.target_reps_min,
                target_reps_max=program_exercise.target_reps_max,
                rest_seconds=program_exercise.rest_seconds,
                last_performance=_build_last_performance(last_performance.get(exercise.id)),
            )
            for program_exercise, exercise in exercise_rows
        ],
    )
