"""Refresh-token data access. §4.4 / §6.3: opaque, single-use, rotated tokens, stored
hashed only. §3: every user-scoped function takes user_id first.
"""

from __future__ import annotations

import uuid
from datetime import datetime

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
