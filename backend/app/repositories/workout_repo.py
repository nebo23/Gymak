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

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.program import Program, ProgramDay
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
    """§5.8: what finish needs to compute duration/volume/counts -- and, until T-19
    adds POST /workouts/{id}/sets, what this task's own tests seed directly (T-18's
    own note: "seed workout_sets directly in the test fixtures to exercise them").
    No `user_id` filter: `workout_sets` carries none of its own (P2-ADR-09),
    ownership already proven by the caller's prior `get_session` lookup.
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
