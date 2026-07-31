"""Social-identity data access (§4.2). §3: repositories are the only place a
SQLAlchemy query is written.

No RLS on user_identities (spec 4.7's note: "users, user_identities and
password_reset_codes have no RLS either: all three are read in pre-auth flows where
app.user_id does not exist yet") -- social sign-in resolves *which* user a request
belongs to by reading this table, so nothing here can already be scoped to a user_id
the caller does not have yet.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import UserIdentity


async def get_by_provider_uid(
    session: AsyncSession, provider: str, provider_uid: str
) -> UserIdentity | None:
    """§5.4 step 3: "Look up user_identities by (provider, provider_uid)." Pre-auth, like
    user_repo.get_by_email -- the caller does not know a user_id until this resolves one.
    """
    result = await session.execute(
        select(UserIdentity).where(
            UserIdentity.provider == provider, UserIdentity.provider_uid == provider_uid
        )
    )
    return result.scalar_one_or_none()


async def list_providers_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """§5.7's `auth_methods`: every provider linked to this user (e.g. ["google"]),
    oldest link first. Ordered by created_at so the result is deterministic rather than
    whatever order the database happens to return -- callers (auth_service.get_me)
    append these after "password", so a stable order here keeps the whole list stable.
    """
    result = await session.execute(
        select(UserIdentity.provider)
        .where(UserIdentity.user_id == user_id)
        .order_by(UserIdentity.created_at)
    )
    return list(result.scalars().all())


async def create_identity(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    provider: str,
    provider_uid: str,
    firebase_uid: str,
    email_at_provider: str | None,
) -> UserIdentity:
    """§5.4 steps 4 and 5: attach a social identity to a user, existing or freshly
    created. §4.2's UNIQUE(provider, provider_uid) is what actually stops the same
    identity attaching to two Gymak users; the caller is responsible for translating the
    resulting IntegrityError into 409 IDENTITY_ALREADY_LINKED (§7.3) -- this function
    only inserts.
    """
    identity = UserIdentity(
        user_id=user_id,
        provider=provider,
        provider_uid=provider_uid,
        firebase_uid=firebase_uid,
        email_at_provider=email_at_provider,
    )
    session.add(identity)
    await session.flush()
    return identity
