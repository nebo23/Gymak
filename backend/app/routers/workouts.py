"""§5.6/§5.7/§5.8 endpoints (P2-FR-005/006/007). Thin HTTP layer only (§3): parse,
enforce the request-level controls (the profile-required gate, the rate limit), call
the service, shape the response. No query is built here.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_completed_profile
from app.core.errors import ExerciseNotFoundError, NotFoundError
from app.core.rate_limit import enforce, key_for_user
from app.models.profile import Profile
from app.models.user import User
from app.repositories import profile_repo
from app.schemas.workout import (
    SessionTotalsData,
    SetRecordData,
    WorkoutAbandonResponse,
    WorkoutFinishRequest,
    WorkoutFinishResponse,
    WorkoutSetActionResponse,
    WorkoutSetCreateRequest,
    WorkoutSetPatchRequest,
    WorkoutStartRequest,
    WorkoutStartResponse,
    build_finished_summary,
    build_session_summary,
    build_set_data,
)
from app.services import workout_service
from app.services.workout_service import SessionNotFoundError, SetActionResult, SetNotFoundError

router = APIRouter(prefix="/workouts", tags=["workouts"])


async def _profile_for(session: AsyncSession, user: User) -> Profile:
    """`require_completed_profile` has already proven this row exists and onboarding
    is complete; re-read here rather than threading Profile through the dependency
    chain, matching routers/program.py's own `_profile_for`."""
    profile = await profile_repo.get_by_user_id(session, user.id)
    assert profile is not None  # guaranteed by require_completed_profile
    return profile


def _rate_limited_for_start(user: Annotated[User, Depends(require_completed_profile)]) -> User:
    """§7.3: "/workouts (POST) ... 20 / hour ... user." No row in that table applies
    to GET /workouts/active, finish, or abandon, so only this route gets one --
    matching routers/program.py's own precedent for /program/generate."""
    enforce(scope="workouts.start", key=key_for_user(user.id), limit=20, window_seconds=3600)
    return user


def _parse_session_id(session_id: str) -> uuid.UUID:
    """§7.2 SESSION_NOT_FOUND covers "unknown session"; a malformed id is treated the
    same way, per §5.2's generic-404 precedent ("every {id} route in T-18 ... follows
    it") -- here using the resource's own specific code, matching
    routers/exercises.py's ExerciseNotFoundError rather than program.py's generic
    NotFoundError, since §7.2 defines SESSION_NOT_FOUND specifically for this
    resource."""
    try:
        return uuid.UUID(session_id)
    except ValueError:
        raise SessionNotFoundError() from None


def _parse_set_id(set_id: str) -> uuid.UUID:
    """Same generic-404 treatment as `_parse_session_id`, for SET_NOT_FOUND (§7.2)."""
    try:
        return uuid.UUID(set_id)
    except ValueError:
        raise SetNotFoundError() from None


def _rate_limited_for_sets(user: Annotated[User, Depends(require_completed_profile)]) -> User:
    """§7.3: "/workouts/*/sets ... 300 / hour ... user" -- applied to POST, PATCH and
    DELETE alike, all three writes to a session's sets sub-resource, matching
    `_rate_limited_for_start`'s own precedent of enforcing directly in a dependency
    ahead of the route body."""
    enforce(scope="workouts.sets", key=key_for_user(user.id), limit=300, window_seconds=3600)
    return user


def _build_set_action_response(result: SetActionResult) -> WorkoutSetActionResponse:
    return WorkoutSetActionResponse(
        set=build_set_data(
            result.workout_set, volume_kg=result.derived.volume_kg, e1rm_kg=result.derived.e1rm_kg
        ),
        session_totals=SessionTotalsData(
            sets=result.totals.set_count, volume_kg=result.totals.volume_kg
        ),
        is_record=(
            SetRecordData(kind=result.record.kind, previous=result.record.previous)
            if result.record is not None
            else None
        ),
    )


@router.post("", response_model=WorkoutStartResponse, status_code=201)
async def start_workout_route(
    body: WorkoutStartRequest,
    user: Annotated[User, Depends(_rate_limited_for_start)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkoutStartResponse:
    profile = await _profile_for(session, user)

    program_day_id: uuid.UUID | None = None
    if body.program_day_id is not None:
        # §5.6: "404 NOT_FOUND if the program_day_id belongs to another user's
        # program -- generic, per Phase 1 §6.5." A malformed value gets the same
        # generic code, matching routers/program.py's own day-id parsing.
        try:
            program_day_id = uuid.UUID(body.program_day_id)
        except ValueError:
            raise NotFoundError(detail="Unknown program day.") from None

    workout_session = await workout_service.start_session(session, user, profile, program_day_id)
    return WorkoutStartResponse(session=build_session_summary(workout_session))


@router.get("/active", response_model=None)
async def get_active_workout_route(
    user: Annotated[User, Depends(require_completed_profile)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkoutStartResponse | Response:
    """§5.1: "the in-progress session, or 204." `response_model=None` so FastAPI
    passes a raw 204 Response straight through instead of trying to validate it
    against a body-carrying model."""
    workout_session = await workout_service.get_active_session(session, user)
    if workout_session is None:
        return Response(status_code=204)
    return WorkoutStartResponse(session=build_session_summary(workout_session))


@router.post("/{session_id}/finish", response_model=WorkoutFinishResponse)
async def finish_workout_route(
    session_id: str,
    body: WorkoutFinishRequest,
    user: Annotated[User, Depends(require_completed_profile)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkoutFinishResponse:
    parsed_id = _parse_session_id(session_id)
    result = await workout_service.finish_session(session, user, parsed_id, body.notes)
    return WorkoutFinishResponse(
        session=build_finished_summary(
            result.session, set_count=result.set_count, exercise_count=result.exercise_count
        )
    )


@router.post("/{session_id}/abandon", response_model=WorkoutAbandonResponse)
async def abandon_workout_route(
    session_id: str,
    user: Annotated[User, Depends(require_completed_profile)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkoutAbandonResponse:
    parsed_id = _parse_session_id(session_id)
    result = await workout_service.abandon_session(session, user, parsed_id)
    return WorkoutAbandonResponse(
        session=build_finished_summary(
            result.session, set_count=result.set_count, exercise_count=result.exercise_count
        )
    )


@router.post("/{session_id}/sets", response_model=WorkoutSetActionResponse, status_code=201)
async def create_set_route(
    session_id: str,
    body: WorkoutSetCreateRequest,
    user: Annotated[User, Depends(_rate_limited_for_sets)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkoutSetActionResponse:
    parsed_session_id = _parse_session_id(session_id)
    # §5.7's own precedent (`exercise_id` stays a bare `str` in the schema): a
    # malformed value gets EXERCISE_NOT_FOUND's generic 404, matching how
    # routers/exercises.py treats a malformed path id.
    try:
        exercise_id = uuid.UUID(body.exercise_id)
    except ValueError:
        raise ExerciseNotFoundError() from None

    result = await workout_service.create_set(
        session,
        user,
        parsed_session_id,
        exercise_id=exercise_id,
        reps=body.reps,
        weight_kg=body.weight_kg,
        rpe=body.rpe,
        is_warmup=body.is_warmup,
    )
    return _build_set_action_response(result)


@router.patch("/{session_id}/sets/{set_id}", response_model=WorkoutSetActionResponse)
async def update_set_route(
    session_id: str,
    set_id: str,
    body: WorkoutSetPatchRequest,
    user: Annotated[User, Depends(_rate_limited_for_sets)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkoutSetActionResponse:
    parsed_session_id = _parse_session_id(session_id)
    parsed_set_id = _parse_set_id(set_id)
    result = await workout_service.update_set(session, user, parsed_session_id, parsed_set_id, body)
    return _build_set_action_response(result)


@router.delete("/{session_id}/sets/{set_id}", status_code=204, response_model=None)
async def delete_set_route(
    session_id: str,
    set_id: str,
    user: Annotated[User, Depends(_rate_limited_for_sets)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    parsed_session_id = _parse_session_id(session_id)
    parsed_set_id = _parse_set_id(set_id)
    await workout_service.delete_set(session, user, parsed_session_id, parsed_set_id)
    return Response(status_code=204)
