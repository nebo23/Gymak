"""Named wrappers over audit_repo for the actions T-04 owns (§4.6's action enum:
user.registered, user.login_succeeded, user.login_failed). One function per action,
rather than a bare action-string call at each call site, so a typo in an action name is
an ImportError/AttributeError at the call site instead of a silent gap in the audit trail.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import audit_repo


async def record_user_registered(
    session: AsyncSession, *, user_id: uuid.UUID, ip: str | None, user_agent: str | None
) -> None:
    await audit_repo.record(
        session,
        action="user.registered",
        actor_user_id=user_id,
        entity="user",
        entity_id=user_id,
        ip=ip,
        user_agent=user_agent,
    )


async def record_login_succeeded(
    session: AsyncSession, *, user_id: uuid.UUID, ip: str | None, user_agent: str | None
) -> None:
    await audit_repo.record(
        session,
        action="user.login_succeeded",
        actor_user_id=user_id,
        entity="user",
        entity_id=user_id,
        ip=ip,
        user_agent=user_agent,
    )


async def record_login_failed(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    reason: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """`user_id` is None when the submitted email does not resolve to a live account
    (§5.3: "actor_user_id null when the email is unknown"). `reason` is a fixed,
    non-secret label -- never the submitted password, which must never reach an audit
    row (§6.5's redaction list, and metadata is app-controlled here, not user input).
    """
    await audit_repo.record(
        session,
        action="user.login_failed",
        actor_user_id=user_id,
        entity="user",
        entity_id=user_id,
        metadata={"reason": reason},
        ip=ip,
        user_agent=user_agent,
    )
