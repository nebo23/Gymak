"""User data access. §3: repositories are the only place a SQLAlchemy query is written.

Created by T-03 with the single function `get_current_user` needs, and extended by T-04
(lookup by email, insert, credential update). It exists this early only so the §3 layering
rule holds from the first line of authenticated code rather than being restored later --
agreed with Nabil before implementing, since T-04 nominally owns this file.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_active_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    """The user behind a verified access token, or None.

    "Active" here means *not soft-deleted* -- §4.1: "A row with deleted_at IS NOT NULL is
    invisible to every query except the purge job." The filter is in the SQL, not left to
    the caller, so no route can forget it. `is_active = false` is a different condition and
    is deliberately NOT filtered here: it must surface as 403 ACCOUNT_DISABLED (§7.3), which
    means the caller needs the row in order to tell the user why.
    """
    result = await session.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    """A live (not soft-deleted) user by email, or None -- §5.2's "a live user already
    holds it" and §5.3's "soft-deleted account returns the same generic 401" both read
    through this one filter. `email` is CITEXT at the database layer (case-insensitive
    already), but the caller still normalises with schemas.auth.normalise_email first
    (§5: "lowercased and trimmed before any lookup or insert") so the same string is used
    for the lookup here and, on register, the insert below.
    """
    result = await session.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str | None,
    email_verified: bool = False,
) -> User:
    """Insert a new user row for §5.2 registration. `id` and the timestamp columns are
    left to their column defaults (P1-ADR-06 / server_default), so this is the only
    construction site a caller needs.
    """
    user = User(email=email, password_hash=password_hash, email_verified=email_verified)
    session.add(user)
    await session.flush()
    return user
