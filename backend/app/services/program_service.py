"""Business logic for spec §5.3 (POST /program/generate), §5.4 (GET /program) and §5.5
(GET /program/days/{day_id}), P2-FR-002/003/004. No HTTP objects here (§3) -- the
router passes plain values and gets a plain dataclass/model back, matching
profile_service.py's convention.

This module is the one permitted to call `plan_generator.generate_plan` (P2-ADR-01's
pure function) and to turn its `PlanGenerationError` into the API's own
`PLAN_GENERATION_FAILED`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError, ValidationError
from app.models.exercise import Exercise
from app.models.profile import Profile
from app.models.program import Program, ProgramDay, ProgramExercise
from app.models.user import User
from app.repositories import audit_repo, program_repo
from app.services.plan_generator import (
    PlanGenerationError,
    PlanInput,
    as_activity_level,
    as_experience_level,
    as_goal,
    generate_plan,
)

# --- error codes new to this task (spec §7.2) ---------------------------------------------
#
# Subclassed here rather than in core/errors.py, which this task's file list does not
# include -- the same pattern app/core/rate_limit.py's RateLimited already uses for
# RATE_LIMIT_EXCEEDED's extra data. Each still renders through the single AppError
# exception handler registered in core/errors.py, which does not care where the
# subclass is defined.


class ProgramNotFoundError(AppError):
    code = "PROGRAM_NOT_FOUND"
    status = 404
    title = "No program has been generated yet"


class SessionActiveBlocksRegenerationError(AppError):
    code = "SESSION_ACTIVE_BLOCKS_REGENERATION"
    status = 409
    title = "An active session is blocking regeneration"


class PlanGenerationFailedError(AppError):
    code = "PLAN_GENERATION_FAILED"
    status = 422
    title = "The exercise library could not satisfy the plan"


_MIN_DAYS_PER_WEEK = 2
_MAX_DAYS_PER_WEEK = 6


def _validate_days_per_week(value: int) -> int:
    """§7.1: "days_per_week integer 2-6, VALIDATION_ERROR / days_per_week:OUT_OF_RANGE."
    Done here, not as a pydantic Field constraint, matching profile_service's own
    convention (schemas/program.py's module docstring): a pydantic validator error
    bypasses the §7.2 envelope."""
    if not (_MIN_DAYS_PER_WEEK <= value <= _MAX_DAYS_PER_WEEK):
        raise ValidationError(
            detail="days_per_week must be between 2 and 6.",
            errors=[{"field": "days_per_week", "code": "OUT_OF_RANGE"}],
        )
    return value


def compute_age(birth_date: date, *, today: date | None = None) -> int:
    """Same computation as profile_service.compute_age (§4.3: "age is computed from
    birth_date, never stored"). Reimplemented rather than imported: profile_service.py
    is not one of this task's files, and importing a service from a service the way
    program_repo.py imports a *type* from plan_generator.py would be a heavier,
    less obviously safe cross-module dependency than re-deriving four lines of pure
    arithmetic that P1-SAF-001 already pins with its own boundary tests.
    """
    as_of = today if today is not None else date.today()
    years = as_of.year - birth_date.year
    if (as_of.month, as_of.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


@dataclass(frozen=True)
class GeneratedProgramResult:
    program: Program
    days: list[ProgramDay]
    exercise_counts: dict[uuid.UUID, int]
    notes_keys: list[str]


async def generate_program(
    session: AsyncSession, user: User, profile: Profile, days_per_week: int
) -> GeneratedProgramResult:
    """§5.3/§6: generate, or regenerate, the caller's plan. Regeneration supersedes
    rather than replaces (§4.3) and is blocked by an `in_progress` session (§5.3,
    P2-ADR-03) -- checked before any generation work happens, since there is no point
    running the generator only to discard its output.
    """
    validated_days_per_week = _validate_days_per_week(days_per_week)

    if await program_repo.has_active_session(session, user.id):
        raise SessionActiveBlocksRegenerationError(
            detail="Finish or abandon the active session before regenerating the plan."
        )

    exercises = await program_repo.list_available_exercises(session)
    available_slugs = frozenset(exercise.slug for exercise in exercises)
    slug_to_exercise_id: dict[str, uuid.UUID] = {
        exercise.slug: exercise.id for exercise in exercises
    }
    slug_to_primary_muscle: dict[str, str] = {
        exercise.slug: exercise.primary_muscle for exercise in exercises
    }

    plan_input = PlanInput(
        experience_level=as_experience_level(profile.experience_level),
        goal=as_goal(profile.goal),
        # profiles.activity_level is nullable (Phase 1 §13.1, unresolved as of this
        # task); "moderate" is the neutral middle of §6.4's five values and is the only
        # reasonable default for a profile that predates the field, since §6.4 requires
        # one to look up a rest adjustment at all.
        activity_level=as_activity_level(profile.activity_level or "moderate"),
        days_per_week=validated_days_per_week,
        age=compute_age(profile.birth_date),
        available_exercise_slugs=available_slugs,
    )

    try:
        plan = generate_plan(plan_input)
    except PlanGenerationError as exc:
        raise PlanGenerationFailedError(detail=str(exc)) from exc

    # §5.3: "Safety P2-SAF-003 is enforced inside the generator, and asserted again by
    # the service before persisting." Recomputed from `slug_to_primary_muscle`, read
    # from the database moments ago -- independent of plan_generator's own internal
    # table, so a bug shared between the two could not hide from both.
    muscle_totals: dict[str, int] = {}
    for day in plan.days:
        for generated_exercise in day.exercises:
            muscle = slug_to_primary_muscle[generated_exercise.slug]
            muscle_totals[muscle] = muscle_totals.get(muscle, 0) + generated_exercise.target_sets
    for muscle, total in muscle_totals.items():
        if total > plan.ceiling_sets_per_muscle_per_week:
            raise PlanGenerationFailedError(
                detail=(
                    f"{muscle} would receive {total} sets/week, exceeding the "
                    f"{plan.ceiling_sets_per_muscle_per_week}-set ceiling."
                )
            )

    await program_repo.supersede_current_program(session, user.id)
    program, days = await program_repo.create_program(
        session,
        user.id,
        days_per_week=validated_days_per_week,
        split_type=plan.split_type,
        goal=profile.goal,
        experience_level=profile.experience_level,
        generator_version=plan.generator_version,
        generated_days=plan.days,
        slug_to_exercise_id=slug_to_exercise_id,
    )
    exercise_counts: dict[uuid.UUID, int] = {
        day.id: len(generated_day.exercises)
        for day, generated_day in zip(days, plan.days, strict=True)
    }

    # §5.3: "program.generated, with days_per_week, split_type, and generator_version
    # in the metadata. Never the exercise list."
    await audit_repo.record(
        session,
        action="program.generated",
        actor_user_id=user.id,
        entity="program",
        entity_id=program.id,
        metadata={
            "days_per_week": validated_days_per_week,
            "split_type": plan.split_type,
            "generator_version": plan.generator_version,
        },
    )
    await session.commit()

    return GeneratedProgramResult(
        program=program,
        days=days,
        exercise_counts=exercise_counts,
        notes_keys=list(plan.notes_keys),
    )


@dataclass(frozen=True)
class CurrentProgramResult:
    program: Program
    days: list[ProgramDay]
    exercise_counts: dict[uuid.UUID, int]
    stale: dict[str, str] | None


def _stale_reason(program: Program, profile: Profile) -> dict[str, str] | None:
    """§5.4: "Includes a stale object when the profile has diverged from the program's
    snapshot ... null when they agree." §4.3 names both `goal` and `experience_level`
    as the snapshotted fields the dashboard compares; the spec's own example shows only
    a goal_changed reason, so where both have diverged this reports goal first (the
    more user-facing of the two) rather than inventing a combined shape the spec never
    describes.
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


async def get_current_program(
    session: AsyncSession, user: User, profile: Profile
) -> CurrentProgramResult:
    """§5.4. `404 PROGRAM_NOT_FOUND` when the user has never generated one."""
    program = await program_repo.get_current_program(session, user.id)
    if program is None:
        raise ProgramNotFoundError(detail="Generate a plan first.")

    days = await program_repo.list_program_days(session, program.id)
    exercise_counts = await program_repo.count_exercises_by_day(session, [day.id for day in days])

    return CurrentProgramResult(
        program=program,
        days=days,
        exercise_counts=exercise_counts,
        stale=_stale_reason(program, profile),
    )


async def get_program_day_detail(
    session: AsyncSession, day_id: uuid.UUID
) -> tuple[ProgramDay, list[tuple[ProgramExercise, Exercise]]]:
    """§5.5. Ownership is enforced by RLS on `program_days`/`program_exercises`
    (P2-ADR-09) -- a day belonging to another user's program resolves to `None` here
    exactly as an unknown id would, so both cases share the same generic 404 (Phase 1
    §6.5), matching the precedent §5.2 sets for GET /exercises/{id}.
    """
    day = await program_repo.get_program_day(session, day_id)
    if day is None:
        raise NotFoundError(detail="Unknown program day.")
    rows = await program_repo.list_day_exercises_with_exercise(session, day.id)
    return day, rows
