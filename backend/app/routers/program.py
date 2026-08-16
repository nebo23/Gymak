"""§5.3-5.5 endpoints (P2-FR-002/003/004). Thin HTTP layer only (§3): parse, enforce
the request-level controls (the profile-required gate, the rate limit), call the
service, shape the response. No query is built here.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_completed_profile
from app.core.errors import NotFoundError
from app.core.rate_limit import enforce, key_for_user
from app.models.profile import Profile
from app.models.user import User
from app.repositories import profile_repo
from app.schemas.program import (
    ProgramDayDetailResponse,
    ProgramGenerateRequest,
    ProgramGenerateResponse,
    ProgramResponse,
    build_program_day_detail,
    build_program_summary,
)
from app.services import program_service

router = APIRouter(prefix="/program", tags=["program"])


async def _profile_for(session: AsyncSession, user: User) -> Profile:
    """`require_completed_profile` has already proven this row exists and onboarding is
    complete (app/core/dependencies.py); re-read here rather than threading Profile
    through the dependency chain, matching routers/exercises.py's `_caller_language`.
    """
    profile = await profile_repo.get_by_user_id(session, user.id)
    assert profile is not None  # guaranteed by require_completed_profile
    return profile


def _rate_limited_for_generate(
    user: Annotated[User, Depends(require_completed_profile)],
) -> User:
    """§7.3: "/program/generate ... 10 / hour ... user." GET /program and GET
    /program/days/{day_id} carry no rate limit in §7.3's table, so only this route
    gets one."""
    enforce(scope="program.generate", key=key_for_user(user.id), limit=10, window_seconds=3600)
    return user


@router.post("/generate", response_model=ProgramGenerateResponse, status_code=201)
async def generate_program_route(
    body: ProgramGenerateRequest,
    user: Annotated[User, Depends(_rate_limited_for_generate)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgramGenerateResponse:
    profile = await _profile_for(session, user)
    result = await program_service.generate_program(session, user, profile, body.days_per_week)
    return ProgramGenerateResponse(
        program=build_program_summary(
            result.program, result.days, result.exercise_counts, result.day_estimated_minutes
        ),
        notes_key=result.notes_keys,
    )


@router.get("", response_model=ProgramResponse)
async def get_current_program_route(
    user: Annotated[User, Depends(require_completed_profile)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgramResponse:
    profile = await _profile_for(session, user)
    result = await program_service.get_current_program(session, user, profile)
    return ProgramResponse(
        program=build_program_summary(
            result.program, result.days, result.exercise_counts, result.day_estimated_minutes
        ),
        stale=result.stale,
    )


@router.get("/days/{day_id}", response_model=ProgramDayDetailResponse)
async def get_program_day_route(
    day_id: str,
    user: Annotated[User, Depends(require_completed_profile)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProgramDayDetailResponse:
    # A malformed id is treated the same as an unknown one -- §6.5's generic-404
    # philosophy, precedented by §5.2's note on GET /exercises/{id}.
    try:
        parsed_day_id = uuid.UUID(day_id)
    except ValueError:
        raise NotFoundError() from None

    profile = await _profile_for(session, user)
    day, exercise_rows, last_performance = await program_service.get_program_day_detail(
        session, parsed_day_id, user.id
    )
    return ProgramDayDetailResponse(
        day=build_program_day_detail(
            day, exercise_rows, language=profile.language, last_performance=last_performance
        )
    )
