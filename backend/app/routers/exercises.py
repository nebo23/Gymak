"""§5.2 endpoints (P2-FR-001), plus the owner-authorised custom-exercise routes
(POST/PATCH/DELETE /exercises -- a deliberate departure from §1.2's "read-only, seeded"
line, authorised for this task and for nothing else in that list). Thin HTTP layer only
(§3): parse, enforce the request-level controls (the profile-required gate, the rate
limit), call the repository, shape the response. No query is built here.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_completed_profile
from app.core.errors import ExerciseNotFoundError, ValidationError
from app.core.rate_limit import enforce, key_for_user
from app.models.exercise import DIFFICULTIES, EQUIPMENT, MOVEMENT_PATTERNS, MUSCLES
from app.models.user import User
from app.repositories import exercise_repo, profile_repo
from app.schemas.exercise import (
    ExerciseCreateRequest,
    ExerciseDeleteResponse,
    ExerciseDetailResponse,
    ExerciseListResponse,
    ExerciseUpdateRequest,
    build_detail,
    build_list_item,
)

router = APIRouter(prefix="/exercises", tags=["exercises"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100

# The four closed vocabularies, taken from models/exercise.py -- the same tuples the
# CHECK constraints are built from. Validating against a second, hand-written copy is
# how a custom row eventually carries a value the rest of the system cannot handle.
_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "primary_muscle": MUSCLES,
    "equipment": EQUIPMENT,
    "movement_pattern": MOVEMENT_PATTERNS,
    "difficulty": DIFFICULTIES,
}


def _rate_limited_user(user: Annotated[User, Depends(require_completed_profile)]) -> User:
    """§7.3: "/exercises ... 120/hour ... user." One row in that table, not one per
    route, so both read routes below share a single scope and counter.
    """
    enforce(scope="exercises", key=key_for_user(user.id), limit=120, window_seconds=3600)
    return user


def _rate_limited_writer(user: Annotated[User, Depends(require_completed_profile)]) -> User:
    """Writes get their own, tighter counter. 30/hour per user is the rate §7.3 already
    gives every other user-scoped write route (PUT /body-weight, PATCH /profile) -- a
    person naming their own exercises does so a handful of times ever, so the read
    allowance of 120 would be a meaningless ceiling here.
    """
    enforce(scope="exercises.write", key=key_for_user(user.id), limit=30, window_seconds=3600)
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


def _parse_exercise_id(exercise_id: str) -> uuid.UUID:
    # A malformed id is treated the same as an unknown one -- spec §6.5's generic-404
    # philosophy for another user's resource applies just as well here: nothing about
    # the shape of a bad identifier deserves a different error than "not found".
    try:
        return uuid.UUID(exercise_id)
    except ValueError:
        raise ExerciseNotFoundError() from None


def _validate_vocabulary_fields(values: dict[str, str | None]) -> list[dict[str, str]]:
    """One §7.2 field error per out-of-vocabulary value. Collected rather than raised on
    the first failure so a client fixing a form sees every bad field at once, which is
    what §7.2's `errors` array is for.
    """
    errors: list[dict[str, str]] = []
    for field, value in values.items():
        if value is not None and value not in _VOCABULARIES[field]:
            errors.append({"field": field, "code": "INVALID"})
    return errors


def _validate_secondary_muscles(muscles: list[str] | None) -> list[dict[str, str]]:
    if muscles is None:
        return []
    if any(muscle not in MUSCLES for muscle in muscles):
        return [{"field": "secondary_muscles", "code": "INVALID"}]
    if len(set(muscles)) != len(muscles):
        return [{"field": "secondary_muscles", "code": "DUPLICATE"}]
    return []


def _assert_valid(errors: list[dict[str, str]]) -> None:
    if errors:
        raise ValidationError(detail="One or more fields are not an accepted value.", errors=errors)


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
    # Returns the seeded library plus this caller's own custom rows; every filter above
    # applies to both alike.
    rows, next_cursor = await exercise_repo.list_active(
        session, user.id, muscle=muscle, equipment=equipment, q=q, limit=limit, cursor=cursor
    )
    return ExerciseListResponse(
        items=[build_list_item(row, language=language) for row in rows],
        next_cursor=next_cursor,
    )


@router.post("", response_model=ExerciseDetailResponse, status_code=201)
async def create_exercise_route(
    body: ExerciseCreateRequest,
    user: Annotated[User, Depends(_rate_limited_writer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExerciseDetailResponse:
    _assert_valid(
        _validate_vocabulary_fields(
            {
                "primary_muscle": body.primary_muscle,
                "equipment": body.equipment,
                "movement_pattern": body.movement_pattern,
                "difficulty": body.difficulty,
            }
        )
        + _validate_secondary_muscles(body.secondary_muscles)
    )

    language = await _caller_language(session, user)
    exercise = await exercise_repo.create_custom(
        session,
        user.id,
        name=body.name.strip(),
        primary_muscle=body.primary_muscle,
        equipment=body.equipment,
        movement_pattern=body.movement_pattern,
        difficulty=body.difficulty,
        is_compound=body.is_compound,
        secondary_muscles=body.secondary_muscles,
        instructions=body.instructions.strip(),
    )
    await session.commit()
    return ExerciseDetailResponse(exercise=build_detail(exercise, language=language))


@router.get("/{exercise_id}", response_model=ExerciseDetailResponse)
async def get_exercise_route(
    exercise_id: str,
    user: Annotated[User, Depends(_rate_limited_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExerciseDetailResponse:
    parsed_id = _parse_exercise_id(exercise_id)
    language = await _caller_language(session, user)
    exercise = await exercise_repo.get_by_id(session, user.id, parsed_id)
    if exercise is None:
        raise ExerciseNotFoundError()
    return ExerciseDetailResponse(exercise=build_detail(exercise, language=language))


@router.patch("/{exercise_id}", response_model=ExerciseDetailResponse)
async def update_exercise_route(
    exercise_id: str,
    body: ExerciseUpdateRequest,
    user: Annotated[User, Depends(_rate_limited_writer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExerciseDetailResponse:
    parsed_id = _parse_exercise_id(exercise_id)
    _assert_valid(
        _validate_vocabulary_fields(
            {
                "primary_muscle": body.primary_muscle,
                "equipment": body.equipment,
                "movement_pattern": body.movement_pattern,
                "difficulty": body.difficulty,
            }
        )
        + _validate_secondary_muscles(body.secondary_muscles)
    )

    language = await _caller_language(session, user)
    # `get_own_by_id`, not `get_by_id`: a seeded row is not the caller's to edit, and it
    # comes back as the same 404 an unknown id would -- never a 403, which would confirm
    # the row exists (§6.5). The explicit `user_id` filter in the repository is defence
    # in depth on top of the p_exercises_own_update RLS policy, not a substitute for it.
    exercise = await exercise_repo.get_own_by_id(session, user.id, parsed_id)
    if exercise is None:
        raise ExerciseNotFoundError()

    await exercise_repo.update_custom(
        session,
        exercise,
        name=body.name.strip() if body.name is not None else None,
        primary_muscle=body.primary_muscle,
        equipment=body.equipment,
        movement_pattern=body.movement_pattern,
        difficulty=body.difficulty,
        is_compound=body.is_compound,
        secondary_muscles=body.secondary_muscles,
        instructions=body.instructions.strip() if body.instructions is not None else None,
    )
    await session.commit()
    return ExerciseDetailResponse(exercise=build_detail(exercise, language=language))


@router.delete("/{exercise_id}", response_model=ExerciseDeleteResponse)
async def delete_exercise_route(
    exercise_id: str,
    user: Annotated[User, Depends(_rate_limited_writer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExerciseDeleteResponse:
    parsed_id = _parse_exercise_id(exercise_id)
    exercise = await exercise_repo.get_own_by_id(session, user.id, parsed_id)
    if exercise is None:
        raise ExerciseNotFoundError()

    # Soft delete (`is_active = false`), never a hard DELETE: workout_sets.exercise_id is
    # ON DELETE RESTRICT, so a logged-against exercise could not be removed anyway, and
    # the app role is not granted DELETE on this table at all.
    await exercise_repo.soft_delete_custom(session, exercise)
    await session.commit()
    return ExerciseDeleteResponse(id=exercise.id, is_active=exercise.is_active)
