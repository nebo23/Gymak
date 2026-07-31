"""Profile data access (§4.3). §3: repositories are the only place a SQLAlchemy query
is written, and every function here takes user_id as its first parameter.

profiles carries FORCE ROW LEVEL SECURITY (§4.7): every function below runs inside a
transaction where app.user_id is already bound. For every route that reaches this
module, that bind happens in app/core/dependencies.py's get_current_user, before the
route handler (and therefore this repository) ever runs -- there is no pre-auth caller
of this module the way user_repo/identity_repo have one for register/login/social. The
explicit `user_id` filter below is defence in depth on top of RLS, not a substitute for
it, matching every other repository in this codebase (§3's own framing: "A route
handler that forgets an ownership check therefore cannot leak data, because there is no
repository function that would let it").
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile


async def get_by_user_id(session: AsyncSession, user_id: uuid.UUID) -> Profile | None:
    """The one-to-one profile row for this user, or None -- §4.3/P1-ADR-03: "A user
    with no profile row is a legitimate state: it means onboarding is unfinished."
    """
    result = await session.execute(select(Profile).where(Profile.user_id == user_id))
    return result.scalar_one_or_none()


async def create_profile(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    gender: str,
    birth_date: date,
    height_cm: Decimal,
    weight_kg: Decimal | None,
    goal: str,
    experience_level: str,
    activity_level: str | None,
    unit_system: str,
    language: str,
) -> Profile:
    """§5.8: insert the one-time onboarding row. `onboarding_completed` is always True
    here -- it "flips true only when every NOT NULL field is satisfied" (§4.3), and this
    is the one place those fields are all supplied together; the caller has already
    validated them (profile_service) before this is reached.
    """
    profile = Profile(
        user_id=user_id,
        name=name,
        gender=gender,
        birth_date=birth_date,
        height_cm=height_cm,
        weight_kg=weight_kg,
        goal=goal,
        experience_level=experience_level,
        activity_level=activity_level,
        unit_system=unit_system,
        language=language,
        onboarding_completed=True,
    )
    session.add(profile)
    await session.flush()
    return profile


async def update_profile(session: AsyncSession, user_id: uuid.UUID, **fields: Any) -> Profile:
    """§5.9 PATCH: apply only the fields the caller passed. Re-fetches rather than
    accepting an ORM instance from the caller, so this stays the only place in the
    codebase that builds a query against `profiles` -- the caller (profile_service)
    works with plain values, the same convention services use everywhere else here.
    """
    result = await session.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one()
    for column, value in fields.items():
        setattr(profile, column, value)
    await session.flush()
    return profile
