"""spec §4.7's note and P2-ADR-04: derived numbers -- e1RM, set volume, session
volume -- are computed on read, never stored. This module holds that arithmetic as
pure functions: no I/O, no randomness, no network, and no import from `models/`,
`repositories/` or `routers/` -- the same boundary P2-ADR-01 states explicitly for
`plan_generator.py`, applied here for the same reason (trivial to unit-test, nothing
to mock).

`session_duration_seconds` lives here too, even though §12's T-18 task text names
only e1RM/set volume/session volume: it is exactly this kind of pure, easily-misread
arithmetic (§5.8: "last_logged_at - started_at, not ended_at - started_at"), and
isolating it here is what makes it independently unit-testable in
tests/unit/test_metrics.py rather than only exercised indirectly through HTTP.

>>> Epley is the reviewed default (P2-ADR-04's own note: "a reasonable default and
>>> Brzycki is a defensible alternative"). Do not swap it for another formula without
>>> a spec change.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True, slots=True)
class SetMetricInput:
    """The three fields §4.7/P2-ADR-04's derived numbers actually need from a set --
    deliberately not `app.models.workout.WorkoutSet` itself, so this module takes no
    dependency on `models/` (see the module docstring's boundary note)."""

    weight_kg: Decimal
    reps: int
    is_warmup: bool


def estimate_one_rep_max(weight_kg: Decimal, reps: int) -> Decimal:
    """P2-ADR-04: "Estimated one-rep max (Epley: weight x (1 + reps/30))." Quantized to
    two decimal places -- weight_kg's own Numeric(6,2) precision -- because reps/30 is
    a repeating decimal for most rep counts, and Decimal's default context otherwise
    leaves a trailing rounding artifact (e.g. 76.00000000000000000000000002) instead of
    the clean 76 the spec's own §5.7 worked example gives.
    """
    raw = weight_kg * (Decimal(30) + Decimal(reps)) / Decimal(30)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def set_volume_kg(weight_kg: Decimal, reps: int) -> Decimal:
    """P2-ADR-04: "set volume (reps x weight)." """
    return weight_kg * Decimal(reps)


def session_volume_kg(sets: Iterable[SetMetricInput]) -> Decimal:
    """P2-ADR-04/§5.8: "the sum over non-warm-up sets only." """
    total = Decimal("0")
    for one_set in sets:
        if not one_set.is_warmup:
            total += set_volume_kg(one_set.weight_kg, one_set.reps)
    return total


def session_duration_seconds(started_at: datetime, last_logged_at: datetime | None) -> int:
    """§5.8, verbatim: "duration_seconds is last_logged_at - started_at, not
    ended_at - started_at ... If the session has no sets, duration is zero." In
    practice `workout_service.finish_session` rejects an empty session before this
    can be called with `last_logged_at=None` (422 EMPTY_SESSION, this task's own
    requirement), but the zero-set case is still handled here directly per §5.8's
    own wording rather than assumed unreachable.
    """
    if last_logged_at is None:
        return 0
    return max(0, int((last_logged_at - started_at).total_seconds()))


# =========================================================================================
# §5.12 `streak` (T-21). workout_sessions.local_date (§4.6) is resolved once, at insert,
# through the profile timezone in effect *then*, and stored -- "so the streak never
# re-derives a timezone at read time" (that model's own docstring). This function is
# therefore pure `date` arithmetic over already-frozen local dates plus one externally
# supplied `today`: it never touches zoneinfo, never subtracts one `datetime` from
# another, and never assumes what "now" is -- the caller (dashboard_service) is the one
# place that resolves `today` through the profile's *current* timezone. Walking `date`
# objects with `timedelta(days=1)` rather than `datetime`/epoch arithmetic is also what
# makes this immune to a DST transition's missing or repeated wall-clock hour -- there is
# no wall-clock hour here to miss or repeat.
# =========================================================================================


@dataclass(frozen=True, slots=True)
class StreakResult:
    current_days: int
    longest_days: int
    last_workout_local_date: date | None


def compute_streak(local_dates: Iterable[date], *, today: date) -> StreakResult:
    """§5.12: "Consecutive calendar days with at least one completed session ... Today
    not yet trained does not break it; yesterday untrained does." `local_dates` may
    contain duplicates (more than one completed session on the same calendar day) --
    deduplicated via `set()` before any run-length arithmetic, since a repeated date
    must count once, not extend a run twice.
    """
    distinct_dates = sorted(set(local_dates))
    if not distinct_dates:
        return StreakResult(current_days=0, longest_days=0, last_workout_local_date=None)

    longest_days = 1
    current_run = 1
    for previous, current in zip(distinct_dates, distinct_dates[1:], strict=False):
        if current == previous + timedelta(days=1):
            current_run += 1
        else:
            current_run = 1
        longest_days = max(longest_days, current_run)

    date_set = set(distinct_dates)
    last_workout_local_date = distinct_dates[-1]

    if today in date_set:
        cursor = today
    elif (today - timedelta(days=1)) in date_set:
        cursor = today - timedelta(days=1)
    else:
        return StreakResult(
            current_days=0,
            longest_days=longest_days,
            last_workout_local_date=last_workout_local_date,
        )

    current_days = 0
    while cursor in date_set:
        current_days += 1
        cursor -= timedelta(days=1)

    return StreakResult(
        current_days=current_days,
        longest_days=longest_days,
        last_workout_local_date=last_workout_local_date,
    )


# =========================================================================================
# §5.12 `next_workout.estimated_minutes` (T-21)
# =========================================================================================


@dataclass(frozen=True, slots=True)
class ProgramDayLoadInput:
    """The two fields §5.12's formula actually needs from a `program_exercises` row --
    deliberately not `app.models.program.ProgramExercise` itself, matching
    `SetMetricInput`'s own precedent of taking plain fields rather than an ORM row so
    this module keeps its no-`models/`-dependency boundary (see the module docstring).
    """

    target_sets: int
    rest_seconds: int


def estimated_session_minutes(entries: Iterable[ProgramDayLoadInput]) -> int:
    """§5.12: "Σ target_sets × (rest_seconds + 40), rounded to five minutes ... It is
    arithmetic over stored targets -- not a prediction." The sum is in seconds
    (`rest_seconds` is seconds, `+ 40` is a per-set working-time estimate in seconds);
    converted to minutes and rounded to the nearest five with the same
    `ROUND_HALF_UP` convention `estimate_one_rep_max`/body_weight_service's moving
    average already use, rather than left to `round()`'s banker's-rounding default.
    """
    total_seconds = sum(entry.target_sets * (entry.rest_seconds + 40) for entry in entries)
    total_minutes = Decimal(total_seconds) / Decimal(60)
    rounded_five_minute_units = (total_minutes / Decimal(5)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(rounded_five_minute_units) * 5
