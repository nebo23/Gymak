"""Business logic for spec §5.6 (POST /workouts, GET /workouts/active) and §5.8
(POST /workouts/{id}/finish, POST /workouts/{id}/abandon), P2-FR-005/007, P2-ADR-03.
No HTTP objects here (§3) -- the router passes plain values and gets a plain
dataclass/model back, matching program_service.py's convention.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.models.profile import Profile
from app.models.user import User
from app.models.workout import WorkoutSession
from app.repositories import workout_repo
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
) -> ClosedSessionResult:
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
    await session.commit()
    return ClosedSessionResult(session=updated, set_count=len(sets), exercise_count=exercise_count)


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
