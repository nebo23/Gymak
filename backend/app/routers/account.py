"""§5.10 DELETE /account (P1-FR-012, §12 T-09c-2). Thin HTTP layer only (§3): parse,
call the service, shape the response. No query is built here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_active
from app.models.user import User
from app.services import auth_service

router = APIRouter(prefix="/account", tags=["account"])


class DeleteAccountRequest(BaseModel):
    """§5.10: "password required when password_hash is not null; omitted for
    social-only accounts." `password` is optional at the schema level -- whether it
    is actually required depends on the authenticated user's row, which the schema
    cannot see, so auth_service.delete_account enforces that. A social-only caller
    still sends a JSON object (`{}`); FastAPI has no body to parse from a request
    with no content at all, only from an empty object.
    """

    model_config = ConfigDict(extra="forbid")

    password: str | None = None


class DeleteAccountResponse(BaseModel):
    """§5.10's exact 202 shape."""

    deletion_requested_at: datetime
    purge_after_days: int = 30


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


@router.delete("", response_model=DeleteAccountResponse, status_code=202)
async def delete_account_route(
    body: DeleteAccountRequest,
    request: Request,
    user: Annotated[User, Depends(require_active)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DeleteAccountResponse:
    result = await auth_service.delete_account(
        session,
        user,
        password=body.password,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return DeleteAccountResponse(
        deletion_requested_at=result.deleted_at, purge_after_days=result.purge_after_days
    )
