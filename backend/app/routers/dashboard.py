"""§5.11 (GET /records) and §5.12 (GET /dashboard), P2-FR-011/012, P2-ADR-05/07. Thin
HTTP layer only (§3): parse, enforce the request-level controls (the profile-required
gate, the rate limit), call the service, shape the response. No query is built here.

Two routers, not one -- `/records` and `/dashboard` are two distinct top-level
resources with their own prefixes -- but both live in this single file because T-21
names one file (`routers/dashboard.py`) for both endpoints (see dashboard_service.py's
own module docstring for why the service layer is likewise unsplit).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_completed_profile
from app.core.errors import ExerciseNotFoundError
from app.core.rate_limit import enforce, key_for_user
from app.models.profile import Profile
from app.models.user import User
from app.repositories import profile_repo
from app.schemas.metrics import (
    DashboardResponse,
    NextWorkoutData,
    RecordsResponse,
    StreakData,
    ThisWeekData,
    build_dashboard_response,
    build_recent_record,
    build_record_entry,
)
from app.services import dashboard_service

records_router = APIRouter(prefix="/records", tags=["records"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _profile_for(session: AsyncSession, user: User) -> Profile:
    """`require_completed_profile` has already proven this row exists and onboarding
    is complete; re-read here rather than threading Profile through the dependency
    chain, matching routers/workouts.py's/routers/body_weight.py's own `_profile_for`.
    """
    profile = await profile_repo.get_by_user_id(session, user.id)
    assert profile is not None  # guaranteed by require_completed_profile
    return profile


async def _caller_language(session: AsyncSession, user: User) -> str:
    """Same resolution as routers/exercises.py's own `_caller_language` --
    reimplemented rather than imported, matching that module's own precedent (a
    router-local helper, not a cross-router import)."""
    profile = await _profile_for(session, user)
    return profile.language


def _rate_limited_for_dashboard(user: Annotated[User, Depends(require_completed_profile)]) -> User:
    """§7.3: "/dashboard ... 120 / hour ... user." No row in that table names
    /records, so only this route gets one -- matching routers/exercises.py's own
    precedent of enforcing only the routes §7.3 actually names."""
    enforce(scope="dashboard", key=key_for_user(user.id), limit=120, window_seconds=3600)
    return user


@records_router.get("", response_model=RecordsResponse)
async def get_records_route(
    user: Annotated[User, Depends(require_completed_profile)],
    session: Annotated[AsyncSession, Depends(get_db)],
    exercise_id: str | None = Query(default=None),
) -> RecordsResponse:
    language = await _caller_language(session, user)

    parsed_exercise_id: uuid.UUID | None = None
    if exercise_id is not None:
        # A malformed filter is treated the same as an unknown exercise (§6.5's
        # generic-404 philosophy, matching routers/exercises.py's own precedent for a
        # malformed path id): there is nothing about the shape of a bad identifier
        # that deserves a different error than "not found".
        try:
            parsed_exercise_id = uuid.UUID(exercise_id)
        except ValueError:
            raise ExerciseNotFoundError() from None

    records = await dashboard_service.get_records(session, user, exercise_id=parsed_exercise_id)
    return RecordsResponse(
        records=[
            build_record_entry(
                exercise=record.exercise,
                language=language,
                heaviest_set=record.heaviest_set,
                heaviest_set_local_date=record.heaviest_set_local_date,
                best_e1rm_set=record.best_e1rm_set,
                best_e1rm_value_kg=record.best_e1rm_value_kg,
                best_e1rm_local_date=record.best_e1rm_local_date,
                best_session_volume_kg=record.best_session_volume_kg,
                best_session_volume_session_id=record.best_session_volume_session_id,
                best_session_volume_local_date=record.best_session_volume_local_date,
                total_sets=record.total_sets,
            )
            for record in records
        ]
    )


@dashboard_router.get("", response_model=DashboardResponse)
async def get_dashboard_route(
    user: Annotated[User, Depends(_rate_limited_for_dashboard)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardResponse:
    profile = await _profile_for(session, user)
    language = profile.language

    result = await dashboard_service.get_dashboard(session, user, profile)

    next_workout = (
        NextWorkoutData(
            program_day_id=result.next_workout.program_day_id,
            day_index=result.next_workout.day_index,
            label_key=result.next_workout.label_key,
            exercise_count=result.next_workout.exercise_count,
            estimated_minutes=result.next_workout.estimated_minutes,
        )
        if result.next_workout is not None
        else None
    )

    return build_dashboard_response(
        greeting_name=result.greeting_name,
        active_session=result.active_session,
        next_workout=next_workout,
        streak=StreakData(
            current_days=result.streak.current_days,
            longest_days=result.streak.longest_days,
            last_workout_local_date=result.streak.last_workout_local_date,
        ),
        this_week=ThisWeekData(
            completed=result.this_week.completed,
            target=result.this_week.target,
            local_week_start=result.this_week.local_week_start,
        ),
        weight=result.weight,
        recent_records=[
            build_recent_record(
                exercise=record.exercise,
                language=language,
                value_kg=record.best_e1rm_value_kg,
                local_date=record.best_e1rm_local_date,
            )
            for record in result.recent_records
        ],
        program_stale=result.program_stale,
        disclaimer_key=result.disclaimer_key,
    )
