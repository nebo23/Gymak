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


async def record_token_refreshed(
    session: AsyncSession, *, user_id: uuid.UUID, ip: str | None, user_agent: str | None
) -> None:
    """§5.5 step 5, on every successful rotation."""
    await audit_repo.record(
        session,
        action="token.refreshed",
        actor_user_id=user_id,
        entity="user",
        entity_id=user_id,
        ip=ip,
        user_agent=user_agent,
    )


async def record_token_reuse_detected(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """§5.5 step 2: a consumed token was presented again. Always paired with
    `record_token_family_revoked` at the call site -- this row records the detection,
    that one records the consequence.
    """
    await audit_repo.record(
        session,
        action="token.reuse_detected",
        actor_user_id=user_id,
        entity="refresh_token_family",
        entity_id=family_id,
        ip=ip,
        user_agent=user_agent,
    )


async def record_token_family_revoked(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID | None,
    reason: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """§4.6's `token.family_revoked` covers every revocation cause this phase has --
    reuse detection, /auth/logout, and /auth/logout-all -- distinguished by `reason`
    rather than by a separate action per cause, since the action enum is fixed.
    `family_id` is None for logout-all, which revokes every family at once rather than
    one chain; the row is then attributed to the user, not a single family.
    """
    await audit_repo.record(
        session,
        action="token.family_revoked",
        actor_user_id=user_id,
        entity="refresh_token_family" if family_id is not None else "user",
        entity_id=family_id if family_id is not None else user_id,
        metadata={"reason": reason},
        ip=ip,
        user_agent=user_agent,
    )
