"""§5.2 endpoints (P2-FR-001). Thin HTTP layer only (§3): parse, enforce the
request-level controls (the profile-required gate, the rate limit), call the
repository, shape the response. No query is built here.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_completed_profile
from app.core.errors import ExerciseNotFoundError
from app.core.rate_limit import enforce, key_for_user
from app.models.user import User
from app.repositories import exercise_repo, profile_repo
from app.schemas.exercise import (
    ExerciseDetailResponse,
    ExerciseListResponse,
    build_detail,
    build_list_item,
)

router = APIRouter(prefix="/exercises", tags=["exercises"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100


def _rate_limited_user(user: Annotated[User, Depends(require_completed_profile)]) -> User:
    """§7.3: "/exercises ... 120/hour ... user." One row in that table, not one per
    route, so both routes below share a single scope and counter.
    """
    enforce(scope="exercises", key=key_for_user(user.id), limit=120, window_seconds=3600)
    return user


async def _caller_language(session: AsyncSession, user: User) -> str:
    """`require_completed_profile` has already proven this row exists and onboarding is
    complete; re-read here rather than threading the Profile through the dependency
    chain, so `require_completed_profile`'s return type stays the same `User` every
    other Phase 2 route will also depend on.
    """
    profile = await profile_repo.get_by_user_id(session, user.id)
    assert profile is not None  # guaranteed by require_completed_profile
    return profile.language


@router.get("", response_model=ExerciseListResponse)
async def list_exercises_route(
    user: Annotated[User, Depends(_rate_limited_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    muscle: str | None = Query(default=None),
    equipment: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(default=None),
) -> ExerciseListResponse:
    language = await _caller_language(session, user)
    rows, next_cursor = await exercise_repo.list_active(
        session, muscle=muscle, equipment=equipment, q=q, limit=limit, cursor=cursor
    )
    return ExerciseListResponse(
        items=[build_list_item(row, language=language) for row in rows],
        next_cursor=next_cursor,
    )


@router.get("/{exercise_id}", response_model=ExerciseDetailResponse)
async def get_exercise_route(
    exercise_id: str,
    user: Annotated[User, Depends(_rate_limited_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExerciseDetailResponse:
    # A malformed id is treated the same as an unknown one -- spec §6.5's generic-404
    # philosophy for another user's resource applies just as well here: nothing about
    # the shape of a bad identifier deserves a different error than "not found".
    try:
        parsed_id = uuid.UUID(exercise_id)
    except ValueError:
        raise ExerciseNotFoundError() from None

    language = await _caller_language(session, user)
    exercise = await exercise_repo.get_by_id(session, parsed_id)
    if exercise is None:
        raise ExerciseNotFoundError()
    return ExerciseDetailResponse(exercise=build_detail(exercise, language=language))
