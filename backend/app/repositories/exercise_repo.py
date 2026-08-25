"""Exercise library data access (spec §4.1, §5.2, P2-ADR-02). §3: repositories are the
only place a query is written.

`exercises` used to be the one table with no owner column and no RLS (§4.10's stated
exception, P2-ADR-09). Migration a1c9f2e4b703 ended that: a row with `user_id IS NULL`
is still seeded public reference data, but a row with `user_id` set belongs to one user.
Every read below therefore takes the caller's `user_id` and filters
`user_id IS NULL OR user_id = :user_id` explicitly -- defence in depth on top of the RLS
policy, the same belt-and-braces §3 requires of every other user-scoped repository, so a
policy that is ever dropped or mis-edited does not silently widen these queries.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
import uuid

import sqlalchemy as sa
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.ids import new_id
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


def _visible_to(user_id: uuid.UUID) -> sa.ColumnElement[bool]:
    """The seeded library plus this caller's own rows. Mirrors the `p_exercises_read`
    RLS policy exactly; written here as well because §3 wants the ownership filter in
    the repository, so these queries stay correct even if the policy is ever dropped.
    """
    return or_(Exercise.user_id.is_(None), Exercise.user_id == user_id)


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_SLUG_BASE_MAX = 40


def _slug_base(name: str) -> str:
    """ASCII-fold the name into slug shape. An Arabic-only name folds away to nothing --
    which is fine and expected: the slug is an internal key (clients render `name`), so
    it falls back to a fixed stem rather than trying to romanise Arabic, which nothing
    here is equipped to do well and which §1.2 forbids reaching for a model to do.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    base = _SLUG_STRIP_RE.sub("-", folded).strip("-")
    return base[:_SLUG_BASE_MAX] or "ex"


def build_custom_slug(user_id: uuid.UUID, exercise_id: uuid.UUID, name: str) -> str:
    """Per-user-prefixed slug for a custom row, chosen over scoping `uq_exercises_slug`
    to `(slug, user_id)`. Two reasons that constraint change was rejected: `UNIQUE
    (slug, user_id)` treats NULLs as distinct by default, so two *seeded* rows could
    then legally share a slug; and `list_active` paginates by keyset on `slug` alone,
    whose no-skip/no-repeat guarantee needs slug to be globally unique.

    The row's own id is folded in as well as the owner's. The user prefix alone would
    still collide when one user creates two exercises whose names slugify identically
    ("Bench Press" and "bench press"), and letting that surface as a failed INSERT is
    exactly the outcome this had to avoid -- so uniqueness comes from the id, which is
    fresh per row, and the prefix stays for legibility and per-user grouping.

    The TAIL of the id, not the head. `new_id()` mints UUID v7, whose leading bits are a
    millisecond timestamp: two exercises created in the same millisecond share their
    first hex characters exactly, so a head slice reintroduced the collision it was
    added to prevent (caught by
    test_two_exercises_with_the_same_name_both_succeed). The last 12 hex characters are
    from the random block.
    """
    return f"custom-{user_id.hex}-{_slug_base(name)}-{exercise_id.hex[-12:]}"


async def list_active(
    session: AsyncSession,
    user_id: uuid.UUID,
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

    Returns the caller's own custom rows alongside the seeded ones, and every filter
    above applies to them identically -- including the Arabic normalisation, since a
    custom row's `name_ar` is a real name like any other.
    """
    stmt = select(Exercise).where(Exercise.is_active.is_(True), _visible_to(user_id))
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


async def get_by_id(
    session: AsyncSession, user_id: uuid.UUID, exercise_id: uuid.UUID
) -> Exercise | None:
    """§5.2: 'GET /exercises/{id} resolves [inactive rows].' No `is_active` filter,
    unlike `list_active` above -- a session logged three months ago must still resolve
    the exercise it names even after the library deactivates it (P2-ADR-02), and that
    applies to a user's own soft-deleted custom exercise for exactly the same reason.

    Another user's custom row is invisible here, which is also what stops a set being
    logged against one: `workout_service.create_set` resolves the exercise through this
    function and raises EXERCISE_NOT_FOUND when it comes back None.
    """
    result = await session.execute(
        select(Exercise).where(Exercise.id == exercise_id, _visible_to(user_id))
    )
    return result.scalar_one_or_none()


async def get_own_by_id(
    session: AsyncSession, user_id: uuid.UUID, exercise_id: uuid.UUID
) -> Exercise | None:
    """The caller's OWN custom row only -- a seeded row (user_id IS NULL) never matches.
    What PATCH and DELETE resolve through, so editing or retiring a seeded row is the
    same generic 404 as an id that does not exist (§6.5: never a 403, which would
    confirm the row is real).
    """
    result = await session.execute(
        select(Exercise).where(Exercise.id == exercise_id, Exercise.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_custom(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    primary_muscle: str,
    equipment: str,
    movement_pattern: str,
    difficulty: str,
    is_compound: bool,
    secondary_muscles: list[str],
    instructions: str,
) -> Exercise:
    """One name in, both language columns filled with it.

    §5.2 resolves the display name server-side from the profile language, and
    `name_en`/`name_ar` are both NOT NULL -- but a user creating an exercise types one
    name, in one language. The alternatives were an empty string in the other column
    (which §5.2's resolver would then render as blank to that user -- the exact failure
    to avoid) or machine-translating it (no LLM call of any kind, §1.2). So the typed
    name is written to both: a user who labels a movement in Arabic sees that label
    whichever language they later switch to, which is what someone naming their own
    exercise actually expects. `instructions_en`/`instructions_ar` are filled the same
    way and default to an empty string when omitted -- empty instructions are a truthful
    "none given", unlike an empty name.
    """
    exercise_id = new_id()
    exercise = Exercise(
        id=exercise_id,
        user_id=user_id,
        slug=build_custom_slug(user_id, exercise_id, name),
        name_en=name,
        name_ar=name,
        primary_muscle=primary_muscle,
        secondary_muscles=secondary_muscles,
        equipment=equipment,
        movement_pattern=movement_pattern,
        is_compound=is_compound,
        difficulty=difficulty,
        instructions_en=instructions,
        instructions_ar=instructions,
        is_active=True,
    )
    session.add(exercise)
    await session.flush()
    return exercise


async def update_custom(
    session: AsyncSession,
    exercise: Exercise,
    *,
    name: str | None,
    primary_muscle: str | None,
    equipment: str | None,
    movement_pattern: str | None,
    difficulty: str | None,
    is_compound: bool | None,
    secondary_muscles: list[str] | None,
    instructions: str | None,
) -> Exercise:
    """Patch semantics: only the fields actually sent are touched. `exercise` must
    already have been resolved through `get_own_by_id`, which is what proves ownership.

    The slug is deliberately NOT regenerated when the name changes. It is an opaque
    internal key -- `list_active`'s pagination cursor is built from it, so a slug that
    moved under a client mid-page would make it skip or repeat rows -- and nothing
    user-visible reads it.
    """
    if name is not None:
        exercise.name_en = name
        exercise.name_ar = name
    if primary_muscle is not None:
        exercise.primary_muscle = primary_muscle
    if equipment is not None:
        exercise.equipment = equipment
    if movement_pattern is not None:
        exercise.movement_pattern = movement_pattern
    if difficulty is not None:
        exercise.difficulty = difficulty
    if is_compound is not None:
        exercise.is_compound = is_compound
    if secondary_muscles is not None:
        exercise.secondary_muscles = secondary_muscles
    if instructions is not None:
        exercise.instructions_en = instructions
        exercise.instructions_ar = instructions
    await session.flush()
    return exercise


async def soft_delete_custom(session: AsyncSession, exercise: Exercise) -> None:
    """`is_active = false`, never a hard DELETE. P2-ADR-02 built this exact mechanism
    for retiring seeded rows and `list_active`/`get_by_id` already honour it, and
    `workout_sets.exercise_id`'s ON DELETE RESTRICT means a custom exercise that has
    been logged against could not be hard-deleted anyway. The app role is not granted
    DELETE on `exercises` at all, so this is enforced by the database, not by habit.
    """
    exercise.is_active = False
    await session.flush()
