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

import sqlalchemy as sa
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.exercise import Exercise

# --- T-16b: Arabic-aware normalisation for §5.2's `q` filter ------------------------------
#
# T-16 reached for `unaccent`, whose default rules file is Latin/Greek/Cyrillic only and
# leaves Arabic untouched -- and Arabic's real matching problems are not diacritics anyway.
# The fix folds the handful of characters Arabic writers vary without changing the word
# (alef variants, yeh, teh marbuta) and drops the marks almost nobody types (harakat,
# tatweel), applied identically to the query (`_normalize_arabic`, below, in Python) and to
# `exercises.name_ar` (`_normalized_name_ar`, in SQL via translate() + regexp_replace()).
# `name_en` needs no such treatment: the seed data carries no accented Latin characters, so
# `unaccent` was not earning the extension slot (spec §5.2's note, §11 item 9) and is
# removed rather than kept "just in case".
_AR_ALEF_VARIANTS = "أإآٱ"
_AR_ALEF = "ا"
_AR_YEH_VARIANT = "ى"
_AR_YEH = "ي"
_AR_TEH_MARBUTA = "ة"
_AR_HEH = "ه"
_AR_FOLD_FROM = _AR_ALEF_VARIANTS + _AR_YEH_VARIANT + _AR_TEH_MARBUTA
_AR_FOLD_TO = (_AR_ALEF * len(_AR_ALEF_VARIANTS)) + _AR_YEH + _AR_HEH
# Harakat U+064B..U+0652, the superscript alef U+0670, and tatweel U+0640 -- stripped, not
# folded, so they carry no `to` counterpart in translate()'s deletion-by-omission behaviour.
_AR_STRIP_PATTERN = "[ً-ْٰـ]"

_AR_TRANSLATE_TABLE = str.maketrans(
    dict(zip(_AR_FOLD_FROM, _AR_FOLD_TO, strict=True))
    | dict.fromkeys(range(0x064B, 0x0653), None)
    | {0x0670: None, 0x0640: None}
)


def _normalize_arabic(text: str) -> str:
    """Python-side twin of `_normalized_name_ar`'s SQL expression below -- must fold and
    strip exactly the same characters, or a query and a stored name that are the same word
    would stop comparing equal."""
    return text.translate(_AR_TRANSLATE_TABLE)


def _normalized_name_ar() -> sa.ColumnElement[str]:
    return func.regexp_replace(
        func.translate(Exercise.name_ar, _AR_FOLD_FROM, _AR_FOLD_TO, type_=sa.Text()),
        _AR_STRIP_PATTERN,
        "",
        "g",
        type_=sa.Text(),
    )


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
    """§5.2: filters combine with AND; `q` matches either language's name,
    case-insensitively via `ILIKE`, and -- for Arabic -- insensitively to alef/yeh/teh
    marbuta variation and harakat/tatweel too (see the `_normalize_arabic`/
    `_normalized_name_ar` pair above this function; T-16b, §5.2's note). Ordered by
    `slug` -- stable and unique, so keyset pagination via `slug > cursor` never skips or
    repeats a row even as rows are added between calls. `is_active = false` rows never
    appear here (§5.2); `get_by_id` below is what resolves them.
    """
    stmt = select(Exercise).where(Exercise.is_active.is_(True))
    if muscle:
        stmt = stmt.where(Exercise.primary_muscle == muscle)
    if equipment:
        stmt = stmt.where(Exercise.equipment == equipment)
    if q:
        # No index backs this scan, and none is added here: the library is ~57 rows
        # (P2-ADR-02 puts it at "~60 movements"), so a sequential scan costs nothing
        # measurable. Revisit with EXPLAIN ANALYZE if the library ever grows past
        # roughly 1,000 rows.
        pattern = f"%{_normalize_arabic(q)}%"
        stmt = stmt.where(
            or_(
                Exercise.name_en.ilike(pattern),
                _normalized_name_ar().ilike(pattern),
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
