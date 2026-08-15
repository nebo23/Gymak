"""Body-weight data access (spec §4.8, §5.10, P2-ADR-06). §3: repositories are the only
place a query is written, and every function here takes user_id explicitly, matching
every other repository in this codebase.

Two upsert functions, not one, because the two P2-ADR-06 writers need different
replace semantics on `note`:

*   `upsert` -- PUT /body-weight (§5.10). The client sent the whole entry; `note` is
    replaced (or cleared) exactly as sent, PUT's own "same-day writes replace"
    contract.
*   `upsert_weight_only` -- PATCH /profile's own weight_kg write (P2-ADR-06's second
    direction). That caller knows only a weight, never a note; blindly setting
    `note=None` on conflict would silently wipe a note a real PUT had stored for
    today, so this variant leaves an existing row's `note` untouched and only
    defaults it to NULL on a fresh insert (nothing to preserve there).

Both use Postgres' native `INSERT ... ON CONFLICT ... DO UPDATE` against
`uq_body_weight_entries_user_measured_on` rather than a select-then-write, so a
same-day double-write race resolves atomically in the database instead of racing two
application-level branches. `updated_at` is left for `trg_body_weight_entries_updated_at`
(migration 88d15c15b877) to set -- the same convention every other mutation in this
codebase already follows, never set by hand here.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.body_weight import BodyWeightEntry

_CONFLICT_CONSTRAINT = "uq_body_weight_entries_user_measured_on"


async def get_by_measured_on(
    session: AsyncSession, user_id: uuid.UUID, measured_on: date
) -> BodyWeightEntry | None:
    result = await session.execute(
        select(BodyWeightEntry).where(
            BodyWeightEntry.user_id == user_id, BodyWeightEntry.measured_on == measured_on
        )
    )
    return result.scalar_one_or_none()


async def get_newest(session: AsyncSession, user_id: uuid.UUID) -> BodyWeightEntry | None:
    """P2-ADR-06: "the entry is the newest one for that user." `measured_on` is
    UNIQUE per user (§4.8), so the newest is unambiguous -- no tie-break needed."""
    result = await session.execute(
        select(BodyWeightEntry)
        .where(BodyWeightEntry.user_id == user_id)
        .order_by(BodyWeightEntry.measured_on.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_in_range(
    session: AsyncSession, user_id: uuid.UUID, *, date_from: date, date_to: date
) -> list[BodyWeightEntry]:
    """Ascending by `measured_on`: what both the chart (oldest-to-newest) and the
    §5.10 `summary` block ("first"/"latest" as the range's own endpoints) need."""
    result = await session.execute(
        select(BodyWeightEntry)
        .where(
            BodyWeightEntry.user_id == user_id,
            BodyWeightEntry.measured_on >= date_from,
            BodyWeightEntry.measured_on <= date_to,
        )
        .order_by(BodyWeightEntry.measured_on.asc())
    )
    return list(result.scalars().all())


async def upsert(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    measured_on: date,
    weight_kg: Decimal,
    note: str | None,
) -> BodyWeightEntry:
    """§5.10 PUT: full replace on conflict, `note` included."""
    stmt = (
        pg_insert(BodyWeightEntry)
        .values(user_id=user_id, measured_on=measured_on, weight_kg=weight_kg, note=note)
        .on_conflict_do_update(
            constraint=_CONFLICT_CONSTRAINT, set_={"weight_kg": weight_kg, "note": note}
        )
        .returning(BodyWeightEntry)
    )
    result = await session.execute(stmt)
    entry = result.scalar_one()
    await session.flush()
    return entry


async def upsert_weight_only(
    session: AsyncSession, user_id: uuid.UUID, *, measured_on: date, weight_kg: Decimal
) -> BodyWeightEntry:
    """P2-ADR-06's second direction: `note` is never touched on an existing row (see
    the module docstring), and defaults to NULL only when this insert creates the row."""
    stmt = (
        pg_insert(BodyWeightEntry)
        .values(user_id=user_id, measured_on=measured_on, weight_kg=weight_kg, note=None)
        .on_conflict_do_update(constraint=_CONFLICT_CONSTRAINT, set_={"weight_kg": weight_kg})
        .returning(BodyWeightEntry)
    )
    result = await session.execute(stmt)
    entry = result.scalar_one()
    await session.flush()
    return entry


async def delete(session: AsyncSession, entry: BodyWeightEntry) -> None:
    await session.delete(entry)
    await session.flush()
