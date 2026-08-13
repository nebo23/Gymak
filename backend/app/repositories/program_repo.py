"""Program data access (spec §4.3-4.5, §5.3-5.5, P2-ADR-01). §3: repositories are the
only place a query is written.

Two reads here reach outside `programs`/`program_days`/`program_exercises`:
`has_active_session` (against `workout_sessions`) and `list_available_exercises`
(against `exercises`). Both are narrow, single-purpose reads this task's own feature
needs -- the regeneration-blocking check (§5.3) and the generator's
`available_exercise_slugs` input (§6.1) -- and neither `workout_repo.py` nor a fuller
`exercise_repo.py` query exists yet for this task to reuse (T-18 and T-16 respectively
own those modules, and are outside this task's file list). A future task that adds
`workout_repo.py` may want to absorb `has_active_session` into it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.program import Program, ProgramDay, ProgramExercise
from app.models.workout import WorkoutSession
from app.services.plan_generator import GeneratedDay


async def has_active_session(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """P2-ADR-03 / §5.3: an `in_progress` session blocks regeneration."""
    result = await session.execute(
        select(WorkoutSession.id).where(
            WorkoutSession.user_id == user_id, WorkoutSession.status == "in_progress"
        )
    )
    return result.first() is not None


async def list_available_exercises(session: AsyncSession) -> list[Exercise]:
    """§6.1: `available_exercise_slugs`, plus what the caller needs to resolve a chosen
    slug back to an `exercise_id` (and, for the belt-and-braces ceiling recheck, a
    `primary_muscle`) when persisting. `is_active` only -- an inactive exercise must
    never be offered to a *new* plan (P2-ADR-02), even though it stays resolvable by id
    for a session that already logged it."""
    result = await session.execute(select(Exercise).where(Exercise.is_active.is_(True)))
    return list(result.scalars().all())


async def get_current_program(session: AsyncSession, user_id: uuid.UUID) -> Program | None:
    result = await session.execute(
        select(Program).where(Program.user_id == user_id, Program.is_current.is_(True))
    )
    return result.scalar_one_or_none()


async def get_program_by_id(session: AsyncSession, program_id: uuid.UUID) -> Program | None:
    result = await session.execute(select(Program).where(Program.id == program_id))
    return result.scalar_one_or_none()


async def supersede_current_program(session: AsyncSession, user_id: uuid.UUID) -> None:
    """§4.3: "Regeneration sets is_current = false and superseded_at = now() on the
    previous row." Must run (and flush) before the new row is inserted --
    `ux_one_current_program` allows only one `is_current = true` row per user at a time.
    """
    current = await get_current_program(session, user_id)
    if current is not None:
        current.is_current = False
        current.superseded_at = datetime.now(UTC)
        await session.flush()


async def create_program(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    days_per_week: int,
    split_type: str,
    goal: str,
    experience_level: str,
    generator_version: int,
    generated_days: Sequence[GeneratedDay],
    slug_to_exercise_id: dict[str, uuid.UUID],
) -> tuple[Program, list[ProgramDay]]:
    """§4.3-4.5: insert the program and every day/exercise beneath it, once, together --
    `program_days`/`program_exercises` are grant-only SELECT+INSERT (never updated
    independently of their parent), so there is no later step that revises a row
    created here."""
    program = Program(
        user_id=user_id,
        days_per_week=days_per_week,
        split_type=split_type,
        goal=goal,
        experience_level=experience_level,
        generator_version=generator_version,
        is_current=True,
    )
    session.add(program)
    await session.flush()

    day_rows: list[ProgramDay] = []
    for generated_day in generated_days:
        day = ProgramDay(
            program_id=program.id,
            day_index=generated_day.day_index,
            label_key=generated_day.label_key,
            focus_muscles=list(generated_day.focus_muscles),
        )
        session.add(day)
        await session.flush()

        for generated_exercise in generated_day.exercises:
            session.add(
                ProgramExercise(
                    program_day_id=day.id,
                    exercise_id=slug_to_exercise_id[generated_exercise.slug],
                    position=generated_exercise.position,
                    target_sets=generated_exercise.target_sets,
                    target_reps_min=generated_exercise.target_reps_min,
                    target_reps_max=generated_exercise.target_reps_max,
                    rest_seconds=generated_exercise.rest_seconds,
                )
            )
        day_rows.append(day)

    await session.flush()
    return program, day_rows


async def list_program_days(session: AsyncSession, program_id: uuid.UUID) -> list[ProgramDay]:
    result = await session.execute(
        select(ProgramDay).where(ProgramDay.program_id == program_id).order_by(ProgramDay.day_index)
    )
    return list(result.scalars().all())


async def count_exercises_by_day(
    session: AsyncSession, program_day_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not program_day_ids:
        return {}
    result = await session.execute(
        select(ProgramExercise.program_day_id, func.count(ProgramExercise.id))
        .where(ProgramExercise.program_day_id.in_(program_day_ids))
        .group_by(ProgramExercise.program_day_id)
    )
    return {program_day_id: count for program_day_id, count in result.all()}


async def get_program_day(session: AsyncSession, day_id: uuid.UUID) -> ProgramDay | None:
    """No explicit `user_id` filter -- `program_days` carries no `user_id` column of its
    own; ownership is enforced by its parent-EXISTS RLS policy (P2-ADR-09), so a day
    belonging to another user's program is already invisible by the time this query
    runs, the same way `exercise_repo.get_by_id` relies on RLS for `exercises` (there,
    the *absence* of RLS is deliberate and public; here, the policy is what does the
    work)."""
    result = await session.execute(select(ProgramDay).where(ProgramDay.id == day_id))
    return result.scalar_one_or_none()


async def list_day_exercises_with_exercise(
    session: AsyncSession, program_day_id: uuid.UUID
) -> list[tuple[ProgramExercise, Exercise]]:
    result = await session.execute(
        select(ProgramExercise, Exercise)
        .join(Exercise, Exercise.id == ProgramExercise.exercise_id)
        .where(ProgramExercise.program_day_id == program_day_id)
        .order_by(ProgramExercise.position)
    )
    return [(program_exercise, exercise) for program_exercise, exercise in result.all()]
