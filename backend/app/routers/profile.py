"""§5.8/§5.9 endpoints. Thin HTTP layer only (§3): parse, enforce the request-level
controls (rate limit), call the service, shape the response. No query is built here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_active
from app.core.rate_limit import enforce, key_for_user
from app.models.user import User
from app.schemas.profile import (
    DerivedFields,
    ProfileCreateRequest,
    ProfileCreateResponse,
    ProfileData,
    ProfileResponse,
    ProfileUpdateRequest,
)
from app.services import profile_service

router = APIRouter(prefix="/profile", tags=["profile"])


def _rate_limited_user(user: Annotated[User, Depends(require_active)]) -> User:
    """§6.4: "/profile ... 30/hour ... user." The user isn't known until require_active
    resolves the bearer token, so -- like /auth/refresh's user-keyed limit -- this can't
    be a plain Depends(rate_limit(...)) keyed off the raw Request. Chaining it as its own
    dependency keeps the limit a single line at each route below, per §6.4's own
    instruction, without needing a second Authorization parse.
    """
    enforce(scope="profile", key=key_for_user(user.id), limit=30, window_seconds=3600)
    return user


@router.post("", response_model=ProfileCreateResponse, status_code=201)
async def create_profile_route(
    body: ProfileCreateRequest,
    user: Annotated[User, Depends(_rate_limited_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProfileCreateResponse:
    profile, age = await profile_service.create_profile(session, user, body)
    return ProfileCreateResponse(
        profile=ProfileData.model_validate(profile), derived=DerivedFields(age=age)
    )


@router.get("", response_model=ProfileResponse)
async def get_profile_route(
    user: Annotated[User, Depends(_rate_limited_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProfileResponse:
    profile = await profile_service.get_profile(session, user)
    return ProfileResponse(profile=ProfileData.model_validate(profile))


@router.patch("", response_model=ProfileResponse)
async def update_profile_route(
    body: ProfileUpdateRequest,
    user: Annotated[User, Depends(_rate_limited_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProfileResponse:
    profile = await profile_service.update_profile(session, user, body)
    return ProfileResponse(profile=ProfileData.model_validate(profile))
