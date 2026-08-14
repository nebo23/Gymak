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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
