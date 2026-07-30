"""Refresh-token data access. §4.4 / §6.3: opaque, single-use, rotated tokens, stored
hashed only. §3: every user-scoped function takes user_id first.

Exception: `get_for_update_by_hash` takes no user_id, because §5.5 step 1 runs before
one is known -- see its docstring, and the migration it depends on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


async def create_refresh_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    token_hash: str,
    family_id: uuid.UUID,
    expires_at: datetime,
    parent_id: uuid.UUID | None = None,
) -> RefreshToken:
    """Insert one token in a rotation chain. `family_id` is constant across the whole
    chain; register and login both start a brand new device session, so `parent_id`
    defaults to None here -- T-05's rotation is what supplies a non-null one.
    """
    token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        family_id=family_id,
        parent_id=parent_id,
        expires_at=expires_at,
    )
    session.add(token)
    await session.flush()
    return token


async def peek_user_id_by_hash(session: AsyncSession, token_hash: str) -> uuid.UUID | None:
    """§5.5 step 1, phase one: discover which user an opaque, not-yet-scoped token
    belongs to. The caller has no bearer and does not know the user yet, so there is no
    value to bind app.user_id to before this runs -- it relies on the permissive
    `FOR SELECT USING (true)` policy migration 6b18a9095bb4 adds, rather than the owner
    policy that governs every write in this module (and every other read: see
    get_for_update_by_hash). This is the one, deliberate exception to the §3
    "user_id first" rule, not a precedent for the rest of the file.

    Deliberately returns *only* the owning user_id, never token state (consumed_at /
    revoked_at / expires_at): this read is unlocked and pre-scope, so nothing here is
    authoritative. The caller must bind app.user_id to the returned id and then call
    get_for_update_by_hash for the read that actually gets acted on.

    Empirically confirmed (not merely reasoned about) that a permissive SELECT policy
    alone is not sufficient for the locked read: PostgreSQL requires a `SELECT ...
    FOR UPDATE` to *also* satisfy whatever policy governs UPDATE on the table, since
    the lock is treated as if performing that command. With app.user_id unbound, the
    owner policy fails that check even though the permissive SELECT policy alone would
    pass a plain SELECT -- so a locked read here, before app.user_id is bound, returns
    nothing regardless of whether the row exists. Hence the two-phase split: an
    unlocked peek to discover the user, then a locked, correctly-scoped read.
    """
    result = await session.execute(
        select(RefreshToken.user_id).where(RefreshToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def get_for_update_by_hash(
    session: AsyncSession, user_id: uuid.UUID, token_hash: str
) -> RefreshToken | None:
    """§5.5 step 1, phase two: the authoritative, locked read spec 5.5 means by "inside
    one database transaction with the row locked." Ordinary owner-scoped lookup, like
    every write in this module -- the caller must have already bound app.user_id to
    `user_id` (via peek_user_id_by_hash on /auth/refresh's pre-auth path, or already
    bound by bearer authentication on /auth/logout's path).

    `user_id` is also in the WHERE clause, not left to RLS alone: on /auth/logout, the
    presented refresh token might belong to a *different* user than the authenticated
    caller, and this filter makes that case indistinguishable from an unknown token
    (returns None) rather than requiring the caller to compare user ids after an
    unfiltered fetch.
    """
    result = await session.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.user_id == user_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def mark_consumed(session: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    """§5.5 step 5. `consumed_at IS NULL` is in the WHERE, not checked after a fetch, so
    a second concurrent exchange of the same token cannot double-consume it even if it
    queued up before this row's FOR UPDATE lock was granted.
    """
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.id == token_id,
            RefreshToken.user_id == user_id,
            RefreshToken.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(UTC))
    )


async def revoke_family(session: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID) -> None:
    """§5.5 step 2 (reuse) and §5's /auth/logout: revoke every still-live token in one
    rotation chain. `revoked_at IS NULL` leaves an already-revoked row's original
    timestamp untouched.
    """
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """§5's /auth/logout-all: every family belonging to this user, not just one chain."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
