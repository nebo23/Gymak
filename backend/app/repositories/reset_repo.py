"""Password reset data access (§4.5, P1-ADR-04, P1-ADR-07, §12 T-07). §3: repositories
are the only place a SQLAlchemy query is written; password_reset_service calls these
and never builds a query itself.

One wrinkle worth stating up front: §4.5 lists six tables total for Phase 1 and none of
them is a reset-token table, yet §6.3 wants the 5-minute reset token "hashed at rest,
single use." Rather than adding a seventh table (out of this task's file list, and
against "nothing else is created in Phase 1"), the *same* `password_reset_codes` row is
reused for both stages of one reset attempt, because a code and its derived token are
never both "live" at once -- the code dies the instant it is redeemed for a token:

  * While `consumed_at IS NULL`: the row is an outstanding CODE. `code_hash` is
    `HMAC-SHA256(pepper, user_id || code)` (P1-ADR-07) and `expires_at` is the code's
    own `RESET_CODE_TTL_SECONDS` deadline, exactly as §4.5 defines them.
  * The moment `verify_code` redeems it, `redeem_code_for_reset_token` overwrites
    `code_hash` with `SHA-256(reset_token)` (plain, unkeyed -- the same
    `hash_opaque_token` refresh tokens use, appropriate here because a 256-bit opaque
    value has nothing to brute-force) and `expires_at` with the token's own, shorter
    `RESET_TOKEN_TTL_SECONDS` deadline. `consumed_at` being non-NULL from that point on
    is what marks the *code* dead; it is never unset or reused as a second flag.
  * `redeem_reset_token` deletes the row outright to spend the token -- a single
    `DELETE ... WHERE ... RETURNING` needs no separate "token consumed" column, and a
    deleted row can never satisfy a second lookup by construction.

`code_hash` and `expires_at` therefore carry two different meanings depending on
`consumed_at`, which is unusual enough that every function below says explicitly which
stage it operates on.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
from app.models.reset_code import PasswordResetCode

DEFAULT_LANGUAGE = "ar"


async def create_code(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    code_hash: str,
    expires_at: datetime,
    requested_ip: str | None,
) -> PasswordResetCode:
    """§5.6 forgot, for an account that is actually eligible (live, has a password)."""
    row = PasswordResetCode(
        user_id=user_id,
        code_hash=code_hash,
        expires_at=expires_at,
        requested_ip=requested_ip,
    )
    session.add(row)
    await session.flush()
    return row


async def consume_previous_unconsumed(session: AsyncSession, user_id: uuid.UUID) -> None:
    """§4.5: "Requesting a new code marks every previous unconsumed code for that user
    as consumed, so only the newest code works." Runs before `create_code` on every
    forgot call for an eligible account, including the very first one (a no-op then).
    """
    await session.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.user_id == user_id, PasswordResetCode.consumed_at.is_(None))
        .values(consumed_at=func.now())
    )


async def get_active_code_for_update(
    session: AsyncSession, user_id: uuid.UUID
) -> PasswordResetCode | None:
    """§5.6 verify-code, primary lookup. `expires_at > now()` is in this WHERE clause,
    not a Python comparison after the fetch (spec's explicit enforcement rule) -- a row
    the database would already reject as expired is never locked or acted on here.
    `FOR UPDATE` is what makes the concurrent-redemption guarantee possible: a second
    transaction racing this one blocks on the same row and, once this one commits the
    redemption in `redeem_code_for_reset_token`, re-evaluates this same WHERE against
    post-commit state and finds nothing (`consumed_at` is no longer NULL) -- exactly
    one winner, by construction, before the belt-and-braces UPDATE guard even runs.
    """
    result = await session.execute(
        select(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user_id,
            PasswordResetCode.consumed_at.is_(None),
            PasswordResetCode.expires_at > func.now(),
        )
        .order_by(PasswordResetCode.created_at.desc())
        .with_for_update()
    )
    return result.scalars().first()


async def get_unconsumed_code_for_update(
    session: AsyncSession, user_id: uuid.UUID
) -> PasswordResetCode | None:
    """§5.6's "attempt_count increments on every failed verify, including expired
    ones" -- called only when `get_active_code_for_update` finds nothing, to locate a
    row that must be expired (the only condition this WHERE drops relative to that
    one) purely so its attempt can still be recorded. No `expires_at` comparison is
    made here either, in Python or SQL: the row's existence under this looser WHERE
    together with its absence under the stricter one is what proves it is expired, not
    a timestamp read-and-compare.
    """
    result = await session.execute(
        select(PasswordResetCode)
        .where(PasswordResetCode.user_id == user_id, PasswordResetCode.consumed_at.is_(None))
        .order_by(PasswordResetCode.created_at.desc())
        .with_for_update()
    )
    return result.scalars().first()


async def increment_attempt(session: AsyncSession, code_id: uuid.UUID) -> None:
    """§5.6: incremented on every failed verify. Callers already hold this row's lock
    via one of the two functions above in the same transaction.
    """
    await session.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.id == code_id)
        .values(attempt_count=PasswordResetCode.attempt_count + 1)
    )


async def redeem_code_for_reset_token(
    session: AsyncSession,
    code_id: uuid.UUID,
    *,
    token_hash: str,
    token_expires_at: datetime,
) -> bool:
    """§5.6: "Set consumed_at in the same UPDATE ... WHERE consumed_at IS NULL that
    redeems the code, and treat a zero-row result as failure." That guard is what this
    function's WHERE enforces; the caller has already located the row (see the module
    docstring for why this UPDATE also repoints `code_hash` and `expires_at` at the
    reset token rather than at the now-dead code). Returns False on a zero-row result
    -- a concurrent request already won this exact redemption.
    """
    result = await session.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.id == code_id, PasswordResetCode.consumed_at.is_(None))
        .values(consumed_at=func.now(), code_hash=token_hash, expires_at=token_expires_at)
    )
    # `session.execute` on an UPDATE is typed as the generic `Result`, but is always a
    # `CursorResult` at runtime for a DML statement against a real DBAPI cursor -- the
    # only place `.rowcount` (needed for the zero-row check above) actually lives.
    return cast("CursorResult[Any]", result).rowcount == 1


async def redeem_reset_token(session: AsyncSession, token_hash: str) -> uuid.UUID | None:
    """§5.6 reset: the single statement that both validates and spends the 5-minute
    reset token. `consumed_at IS NOT NULL` selects only rows already past the
    verify-code stage (see the module docstring); `expires_at > now()` is this stage's
    own deadline, in the WHERE for the same reason the code's is. DELETE rather than
    another UPDATE ... WHERE flag: a deleted row cannot satisfy a second lookup by
    definition, so no further column is needed to mark the token spent, and a second,
    concurrent call against the same token deletes zero rows and gets None back --
    "reuse of a spent reset token" and "double redemption" collapse to the same
    zero-row case here for the same reason they do in `redeem_code_for_reset_token`.
    """
    result = await session.execute(
        delete(PasswordResetCode)
        .where(
            PasswordResetCode.code_hash == token_hash,
            PasswordResetCode.consumed_at.is_not(None),
            PasswordResetCode.expires_at > func.now(),
        )
        .returning(PasswordResetCode.user_id)
    )
    return result.scalar_one_or_none()


async def get_language_for_user(session: AsyncSession, user_id: uuid.UUID) -> str:
    """§4.3 / §9.6: the language an email should render in. No `profile_repo.py` exists
    yet (T-08's territory), and every account is mid-onboarding until then (see
    `auth_service._issue_session`'s docstring), so this is a one-column read living
    here rather than a whole repository built early for a single call site. Defaults
    to Arabic (§4.3's own column default, and decision 13.1 §13.2 item 7) when no
    profile row exists yet, which is the common case in Phase 1.
    """
    result = await session.execute(select(Profile.language).where(Profile.user_id == user_id))
    language = result.scalar_one_or_none()
    return language or DEFAULT_LANGUAGE
