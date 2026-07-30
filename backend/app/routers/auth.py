"""§5.2/§5.3 endpoints. Thin HTTP layer only (§3): parse, enforce the request-level
controls (rate limits), call the service, shape the response. No query is built here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.rate_limit import enforce, ip_key, key_for_email, rate_limit
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPairResponse, UserSummary
from app.services import auth_service
from app.services.auth_service import IssuedSession

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _to_response(issued: IssuedSession) -> TokenPairResponse:
    return TokenPairResponse(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        refresh_token=issued.refresh_token,
        refresh_expires_in=issued.refresh_expires_in,
        user=UserSummary(
            id=issued.user.id,
            email=issued.user.email,
            onboarding_completed=issued.onboarding_completed,
        ),
    )


@router.post(
    "/register",
    response_model=TokenPairResponse,
    status_code=201,
    # §6.4: 5/hour, keyed on IP.
    dependencies=[Depends(rate_limit("auth.register", limit=5, window_seconds=3600))],
)
async def register_route(
    body: RegisterRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPairResponse:
    issued = await auth_service.register(
        session, body, ip=_client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return _to_response(issued)


@router.post("/login", response_model=TokenPairResponse)
async def login_route(
    body: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPairResponse:
    # §6.4: "10 / 15 min ... IP + email, whichever trips first." Both are counted
    # against the SUBMITTED address before the service ever looks the user up, using
    # `enforce()` directly rather than the `rate_limit()` dependency, because the email
    # half needs the parsed body -- the same reason §5.6's forgot-password limit does.
    enforce(scope="auth.login", key=ip_key(request), limit=10, window_seconds=900)
    enforce(scope="auth.login", key=key_for_email(body.email), limit=10, window_seconds=900)

    issued = await auth_service.login(
        session, body, ip=_client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return _to_response(issued)
