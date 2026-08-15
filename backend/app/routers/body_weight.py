"""§5.10 endpoints (P2-FR-009/010), P2-ADR-06. Thin HTTP layer only (§3): parse,
enforce the request-level controls (the profile-required gate, the rate limit), call
the service, shape the response. No query is built here.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_completed_profile
from app.core.errors import NotFoundError
from app.core.rate_limit import enforce, key_for_user
from app.models.profile import Profile
from app.models.user import User
from app.repositories import profile_repo
from app.schemas.metrics import (
    BodyWeightListResponse,
    BodyWeightPoint,
    BodyWeightSummaryData,
    BodyWeightUpsertRequest,
    BodyWeightUpsertResponse,
    build_entry_data,
)
from app.services import body_weight_service

router = APIRouter(prefix="/body-weight", tags=["body-weight"])


async def _profile_for(session: AsyncSession, user: User) -> Profile:
    """`require_completed_profile` has already proven this row exists and onboarding
    is complete; re-read here rather than threading Profile through the dependency
    chain, matching routers/workouts.py's and routers/program.py's own `_profile_for`.
    """
    profile = await profile_repo.get_by_user_id(session, user.id)
    assert profile is not None  # guaranteed by require_completed_profile
    return profile


def _rate_limited_for_put(user: Annotated[User, Depends(require_completed_profile)]) -> User:
    """§7.3: "/body-weight (PUT) ... 30 / hour ... user." No row in that table applies
    to GET or DELETE, so only PUT gets one -- matching routers/workouts.py's own
    precedent of enforcing only the routes §7.3 actually names."""
    enforce(scope="body_weight.put", key=key_for_user(user.id), limit=30, window_seconds=3600)
    return user


def _parse_measured_on(raw: str) -> date:
    """No §7.2 code names a body-weight-specific 404; a malformed or unknown day both
    resolve to the generic NOT_FOUND, per Phase 1 §6.5's precedent for exactly this
    "malformed and unknown are indistinguishable to the caller" shape."""
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise NotFoundError(detail="Unknown body-weight entry.") from None


@router.put("", response_model=BodyWeightUpsertResponse)
async def upsert_body_weight_route(
    body: BodyWeightUpsertRequest,
    user: Annotated[User, Depends(_rate_limited_for_put)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BodyWeightUpsertResponse:
    profile = await _profile_for(session, user)
    entry, profile_weight_updated = await body_weight_service.upsert_entry(
        session,
        user,
        profile,
        measured_on_raw=body.measured_on,
        weight_kg=body.weight_kg,
        note=body.note,
    )
    return BodyWeightUpsertResponse(
        entry=build_entry_data(entry), profile_weight_updated=profile_weight_updated
    )


@router.get("", response_model=BodyWeightListResponse)
async def list_body_weight_route(
    user: Annotated[User, Depends(require_completed_profile)],
    session: Annotated[AsyncSession, Depends(get_db)],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> BodyWeightListResponse:
    profile = await _profile_for(session, user)
    result = await body_weight_service.get_entries_in_range(
        session, user, profile, date_from=date_from, date_to=date_to
    )
    return BodyWeightListResponse(
        entries=[
            BodyWeightPoint(measured_on=e.measured_on, weight_kg=e.weight_kg)
            for e in result.entries
        ],
        moving_average_7d=[
            BodyWeightPoint(measured_on=p.measured_on, weight_kg=p.weight_kg)
            for p in result.moving_average
        ],
        summary=BodyWeightSummaryData(
            first=result.summary.first,
            latest=result.summary.latest,
            change_kg=result.summary.change_kg,
            entry_count=result.summary.entry_count,
        ),
    )


@router.delete("/{measured_on}", status_code=204, response_model=None)
async def delete_body_weight_route(
    measured_on: str,
    user: Annotated[User, Depends(require_completed_profile)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    parsed = _parse_measured_on(measured_on)
    await body_weight_service.delete_entry(session, user, parsed)
    return Response(status_code=204)
