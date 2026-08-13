"""Exercise library data access (spec §4.1, §5.2, P2-ADR-02). §3: repositories are the
only place a query is written.

Unlike every other repository in this codebase, no function here takes a `user_id`:
`exercises` carries no RLS and no owner column (§4.10's stated exception) -- it is
public reference data, readable by any authenticated caller.
"""

from __future__ import annotations

import base64
import binascii
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.exercise import Exercise


def encode_cursor(slug: str) -> str:
    """The cursor is an opaque, base64-wrapped copy of the last row's `slug` -- the
    same column `list_active` orders and filters by, so paging never needs a second,
    different key to stay stable while the underlying table changes between pages.
    """
    return base64.urlsafe_b64encode(slug.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationError(
            detail="cursor is not a value this endpoint issued.",
            errors=[{"field": "cursor", "code": "INVALID"}],
        ) from exc


async def list_active(
    session: AsyncSession,
    *,
    muscle: str | None,
    equipment: str | None,
    q: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[Exercise], str | None]:
    """§5.2: filters combine with AND; `q` matches either language's name, case- and
    diacritic-insensitively (via the `unaccent` extension, seeded alongside T-16's data
    migration). Ordered by `slug` -- stable and unique, so keyset pagination via
    `slug > cursor` never skips or repeats a row even as rows are added between calls.
    `is_active = false` rows never appear here (§5.2); `get_by_id` below is what
    resolves them.
    """
    stmt = select(Exercise).where(Exercise.is_active.is_(True))
    if muscle:
        stmt = stmt.where(Exercise.primary_muscle == muscle)
    if equipment:
        stmt = stmt.where(Exercise.equipment == equipment)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                func.unaccent(Exercise.name_en).ilike(func.unaccent(pattern)),
                func.unaccent(Exercise.name_ar).ilike(func.unaccent(pattern)),
            )
        )
    if cursor:
        stmt = stmt.where(Exercise.slug > decode_cursor(cursor))
    # One extra row fetched, never returned: its mere presence is what tells the
    # caller a next page exists, without a second COUNT-style query.
    stmt = stmt.order_by(Exercise.slug).limit(limit + 1)

    rows = list((await session.execute(stmt)).scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].slug)
    return rows, next_cursor


async def get_by_id(session: AsyncSession, exercise_id: uuid.UUID) -> Exercise | None:
    """§5.2: 'GET /exercises/{id} resolves [inactive rows].' No `is_active` filter,
    unlike `list_active` above -- a session logged three months ago must still be able
    to resolve the exercise it names even after the library deactivates it (P2-ADR-02).
    """
    result = await session.execute(select(Exercise).where(Exercise.id == exercise_id))
    return result.scalar_one_or_none()
