"""Business logic for spec §5.10 (PUT/GET/DELETE /body-weight), P2-FR-009/010,
P2-ADR-06. No HTTP objects here (§3) -- the router passes plain values and gets a
plain dataclass/model back, matching workout_service.py's own convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.body_weight import BodyWeightEntry
from app.models.profile import Profile
from app.models.user import User
from app.repositories import body_weight_repo, profile_repo

# =========================================================================================
# §7.1 field validation. Same `_field_error` shape as profile_service's/workout_service's
# own copies -- not imported from either (neither is a dependency of this module, matching
# workout_service.validate_set_weight_kg's own precedent of a private copy rather than a
# cross-service import, even where a bound happens to coincide).
# =========================================================================================

_MIN_WEIGHT_KG = Decimal("30")
_MAX_WEIGHT_KG = Decimal("300")
_MIN_MEASURED_ON = date(2000, 1, 1)
_MAX_NOTE_LENGTH = 200


def _field_error(field: str, code: str, detail: str) -> ValidationError:
    return ValidationError(detail=detail, errors=[{"field": field, "code": code}])


def _today_local(timezone_name: str) -> date:
    """§5.10: "resolved against the user's timezone, so a user in Cairo at 01:00 can
    log 'today' without the UTC server calling it tomorrow." The same
    now-then-astimezone-then-date shape workout_service.start_session already uses for
    `local_date` (§4.2)."""
    return datetime.now(UTC).astimezone(ZoneInfo(timezone_name)).date()


def validate_weight_kg(value: Decimal) -> Decimal:
    """§7.1: "weight_kg (body): 30-300 ... the same range as the profile.\""""
    if not (_MIN_WEIGHT_KG <= value <= _MAX_WEIGHT_KG):
        raise _field_error("weight_kg", "OUT_OF_RANGE", "weight_kg must be between 30 and 300.")
    return value


def validate_measured_on(raw: str, *, today_local: date) -> date:
    """§7.1: "measured_on: ISO date, not in the future in the user's timezone, not
    before 2000-01-01." One error code, `measured_on:IN_FUTURE`, is all §7.1 names for
    this row -- the same precedent profile_service.validate_birth_date already set
    ("a malformed string and an out-of-range date both surface as ... the spec defines
    no separate code") applied to this field's own single given code. `today_local` is
    a parameter, not read internally, so the caller is the one place that resolves
    "now" through the profile's timezone.
    """
    try:
        parsed = date.fromisoformat(raw)
    except (ValueError, TypeError) as exc:
        raise _field_error(
            "measured_on", "IN_FUTURE", "Enter a valid date (YYYY-MM-DD), not in the future."
        ) from exc
    if parsed > today_local or parsed < _MIN_MEASURED_ON:
        raise _field_error(
            "measured_on",
            "IN_FUTURE",
            "measured_on must not be in the future, and not before 2000-01-01.",
        )
    return parsed


def validate_note(raw: str | None) -> str | None:
    """§4.8: "note text NULL, <= 200 chars." No §7.1 row names a code for this field
    specifically -- that table's own `notes:TOO_LONG` row is workout_sessions.notes, a
    different column with a different, 500-char bound (§4.6). `note:TOO_LONG` mirrors
    that row's own `<field>:<reason>` convention for body weight's differently-named,
    differently-bounded column. An empty-after-trim string is "no note", not a stored
    empty string.
    """
    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    if len(trimmed) > _MAX_NOTE_LENGTH:
        raise _field_error(
            "note", "TOO_LONG", f"note must be {_MAX_NOTE_LENGTH} characters or fewer."
        )
    return trimmed


# =========================================================================================
# §5.10 PUT /body-weight, P2-ADR-06
# =========================================================================================


async def upsert_entry(
    session: AsyncSession,
    user: User,
    profile: Profile,
    *,
    measured_on_raw: str,
    weight_kg: Decimal,
    note: str | None,
) -> tuple[BodyWeightEntry, bool]:
    """§5.10 PUT. Upsert the entry, then check whether it is still the newest for this
    user -- in the same transaction, so this read sees this write (P2-ADR-06: "written
    in the same transaction as the entry itself"). `profiles.weight_kg` is written only
    when it is.
    """
    today_local = _today_local(profile.timezone)
    measured_on = validate_measured_on(measured_on_raw, today_local=today_local)
    validated_weight = validate_weight_kg(weight_kg)
    validated_note = validate_note(note)

    entry = await body_weight_repo.upsert(
        session, user.id, measured_on=measured_on, weight_kg=validated_weight, note=validated_note
    )
    newest = await body_weight_repo.get_newest(session, user.id)
    profile_weight_updated = newest is not None and newest.id == entry.id
    if profile_weight_updated:
        await profile_repo.update_profile(session, user.id, weight_kg=validated_weight)

    await session.commit()
    return entry, profile_weight_updated


# =========================================================================================
# §5.10 DELETE /body-weight/{measured_on}
# =========================================================================================


async def delete_entry(session: AsyncSession, user: User, measured_on: date) -> None:
    """§5.10 DELETE, this task's own requirement: "deleting the newest entry rolls
    profiles.weight_kg back to the next newest, or leaves it unchanged when no entry
    remains." Deleting anything else leaves profiles.weight_kg untouched -- it is
    already caught up with the true newest entry either way.
    """
    entry = await body_weight_repo.get_by_measured_on(session, user.id, measured_on)
    if entry is None:
        raise NotFoundError(detail="Unknown body-weight entry.")

    newest = await body_weight_repo.get_newest(session, user.id)
    was_newest = newest is not None and newest.id == entry.id

    await body_weight_repo.delete(session, entry)

    if was_newest:
        next_newest = await body_weight_repo.get_newest(session, user.id)
        if next_newest is not None:
            await profile_repo.update_profile(session, user.id, weight_kg=next_newest.weight_kg)
        # else: no entry remains -- profiles.weight_kg is left exactly as it was.

    await session.commit()


# =========================================================================================
# §5.10 GET /body-weight
# =========================================================================================

_DEFAULT_RANGE_DAYS = 90
_MAX_RANGE_DAYS = 730
_MOVING_AVERAGE_WINDOW_DAYS = 7
_MIN_POINTS_IN_WINDOW = 3


@dataclass(frozen=True)
class MovingAveragePoint:
    measured_on: date
    weight_kg: Decimal


@dataclass(frozen=True)
class BodyWeightSummary:
    first: Decimal | None
    latest: Decimal | None
    change_kg: Decimal | None
    entry_count: int


@dataclass(frozen=True)
class BodyWeightRangeResult:
    entries: list[BodyWeightEntry]
    moving_average: list[MovingAveragePoint]
    summary: BodyWeightSummary


async def get_entries_in_range(
    session: AsyncSession,
    user: User,
    profile: Profile,
    *,
    date_from: date | None,
    date_to: date | None,
) -> BodyWeightRangeResult:
    """§5.10 GET. Range defaults to the trailing 90 days, ending "today" in the
    caller's own timezone (§4.2) -- the same boundary PUT's future check uses. A span
    wider than 730 days is clamped from the older end rather than rejected: §7.1 names
    no error code for this bound, and "maximum span 730 days" reads as a ceiling on
    what comes back, not a reason to fail an otherwise-valid request for old data.
    """
    today_local = _today_local(profile.timezone)
    resolved_to = date_to if date_to is not None else today_local
    resolved_from = (
        date_from if date_from is not None else resolved_to - timedelta(days=_DEFAULT_RANGE_DAYS)
    )
    if (resolved_to - resolved_from).days > _MAX_RANGE_DAYS:
        resolved_from = resolved_to - timedelta(days=_MAX_RANGE_DAYS)

    # Extended lookback so the moving average for the first few in-range days can still
    # see the up-to-6-days-earlier entries their trailing window needs, without leaking
    # those earlier entries into the returned `entries` list itself.
    lookback_start = resolved_from - timedelta(days=_MOVING_AVERAGE_WINDOW_DAYS - 1)
    extended = await body_weight_repo.list_in_range(
        session, user.id, date_from=lookback_start, date_to=resolved_to
    )
    entries = [e for e in extended if e.measured_on >= resolved_from]

    return BodyWeightRangeResult(
        entries=entries,
        moving_average=_compute_moving_average(extended, entries),
        summary=_compute_summary(entries),
    )


def _compute_moving_average(
    extended: list[BodyWeightEntry], in_range: list[BodyWeightEntry]
) -> list[MovingAveragePoint]:
    """§5.10: "seven-day trailing, computed only where at least three entries exist in
    the window ... days with no entry are not interpolated -- the array is sparse." One
    point per day that HAS an entry (never a day without one), so a gap in the raw log
    stays a gap here too.
    """
    points: list[MovingAveragePoint] = []
    for entry in in_range:
        window_start = entry.measured_on - timedelta(days=_MOVING_AVERAGE_WINDOW_DAYS - 1)
        window_values = [
            e.weight_kg for e in extended if window_start <= e.measured_on <= entry.measured_on
        ]
        if len(window_values) >= _MIN_POINTS_IN_WINDOW:
            average = sum(window_values, Decimal(0)) / Decimal(len(window_values))
            points.append(
                MovingAveragePoint(
                    measured_on=entry.measured_on,
                    weight_kg=average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                )
            )
    return points


def _compute_summary(entries: list[BodyWeightEntry]) -> BodyWeightSummary:
    """§5.10's `summary` block, over the entries actually in range -- an empty range is
    a well-formed zero shape (schemas/metrics.py's own note), never an error."""
    if not entries:
        return BodyWeightSummary(first=None, latest=None, change_kg=None, entry_count=0)
    first = entries[0].weight_kg
    latest = entries[-1].weight_kg
    return BodyWeightSummary(
        first=first, latest=latest, change_kg=latest - first, entry_count=len(entries)
    )
