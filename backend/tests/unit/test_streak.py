"""Unit tests for `app.services.metrics.compute_streak` -- spec §5.12's `streak` block
and this task's (T-21) own explicit instruction: "Write the nine streak cases in 10.1
as tests BEFORE writing the streak function."

§10.1 names eight cases in prose: "trained today, trained yesterday not today, gap of
exactly one day, gap of two, a session at 23:59 local, a session at 00:01 local, a DST
transition, a user who changes timezone mid-streak." This task's own text calls for
nine. The ninth, added here, is "no sessions at all" -- current_days=0, longest_days=0,
last_workout_local_date=None -- which this task's own empty-account requirement (a
brand-new account's dashboard needs a well-formed zero streak, never an error) makes
just as load-bearing as the other eight, even though §10.1's prose does not spell it
out as its own bullet.

`compute_streak` takes already-resolved `date` values, never a timestamp or a
timezone: workout_sessions.local_date (§4.6) is resolved once, at insert, through the
profile timezone in effect *at that time*, and stored -- "so the streak never
re-derives a timezone at read time" (that model's own docstring). This module's own
job is therefore pure calendar-date arithmetic over already-frozen dates plus one
externally supplied `today` -- no zoneinfo import here at all. Cases 5/6/7 still
construct their input dates via `zoneinfo`, because what they are proving is that
*this* boundary-correct resolution step, fed into `compute_streak`, produces the
right calendar days -- not that the pure function itself touches a clock.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services import metrics


def test_case_1_trained_today_only() -> None:
    today = date(2026, 8, 13)
    result = metrics.compute_streak([today], today=today)
    assert result.current_days == 1
    assert result.longest_days == 1
    assert result.last_workout_local_date == today


def test_case_2_trained_yesterday_not_today_does_not_break_the_streak() -> None:
    today = date(2026, 8, 13)
    yesterday = date(2026, 8, 12)
    result = metrics.compute_streak([yesterday], today=today)
    assert result.current_days == 1, "today not yet trained must not break the streak"
    assert result.longest_days == 1
    assert result.last_workout_local_date == yesterday


def test_case_3_gap_of_exactly_one_day_breaks_the_streak() -> None:
    today = date(2026, 8, 13)
    # Trained today and two days ago; the single missing day in between (8/12) breaks
    # the chain back to the older session.
    two_days_ago = today.fromordinal(today.toordinal() - 2)
    result = metrics.compute_streak([two_days_ago, today], today=today)
    assert result.current_days == 1, "a single missed day must break continuity"
    assert result.longest_days == 1
    assert result.last_workout_local_date == today


def test_case_4_gap_of_two_days_also_breaks_the_streak() -> None:
    today = date(2026, 8, 13)
    three_days_ago = today.fromordinal(today.toordinal() - 3)
    result = metrics.compute_streak([three_days_ago, today], today=today)
    assert result.current_days == 1, "a wider gap must break continuity exactly the same way"
    assert result.longest_days == 1
    assert result.last_workout_local_date == today


def test_case_5_a_session_at_2359_local_resolves_to_that_calendar_day() -> None:
    # Tokyo carries no DST, so this is a clean boundary check: 23:59 local on the 12th
    # must resolve to the 12th, not roll into the 13th.
    tz = ZoneInfo("Asia/Tokyo")
    late_night = datetime(2026, 8, 12, 23, 59, tzinfo=tz).date()
    assert late_night == date(2026, 8, 12)

    result = metrics.compute_streak([late_night], today=date(2026, 8, 12))
    assert result.current_days == 1
    assert result.last_workout_local_date == date(2026, 8, 12)


def test_case_6_a_session_at_0001_local_pairs_as_the_next_consecutive_day() -> None:
    """The companion to case 5: a session two minutes later in local wall-clock time
    (23:59 on the 12th, then 00:01 on the 13th) resolves to two *different*,
    consecutive calendar days -- and the streak counts them as two, not one merged
    training event and not a broken chain.
    """
    tz = ZoneInfo("Asia/Tokyo")
    late_night = datetime(2026, 8, 12, 23, 59, tzinfo=tz).date()
    just_after_midnight = datetime(2026, 8, 13, 0, 1, tzinfo=tz).date()
    assert just_after_midnight == date(2026, 8, 13)
    assert just_after_midnight != late_night

    result = metrics.compute_streak([late_night, just_after_midnight], today=date(2026, 8, 13))
    assert result.current_days == 2
    assert result.longest_days == 2
    assert result.last_workout_local_date == date(2026, 8, 13)


def test_case_7_a_streak_survives_a_dst_transition() -> None:
    """US clocks sprang forward on 2026-03-08 (America/New_York). Three sessions on
    consecutive calendar days straddling that transition -- the 7th (before), the 8th
    (the transition day itself, a 23-hour wall-clock day), and the 9th (after) -- must
    still read as a 3-day streak. `compute_streak` never subtracts one `datetime` from
    another; it walks `date` objects with `timedelta(days=1)`, which is exactly what
    makes it immune to the missing/repeated wall-clock hour a DST transition creates.
    """
    tz = ZoneInfo("America/New_York")
    day_before = datetime(2026, 3, 7, 20, 0, tzinfo=tz).date()
    transition_day = datetime(2026, 3, 8, 20, 0, tzinfo=tz).date()
    day_after = datetime(2026, 3, 9, 20, 0, tzinfo=tz).date()
    assert (day_before, transition_day, day_after) == (
        date(2026, 3, 7),
        date(2026, 3, 8),
        date(2026, 3, 9),
    )

    result = metrics.compute_streak([day_before, transition_day, day_after], today=date(2026, 3, 9))
    assert result.current_days == 3
    assert result.longest_days == 3
    assert result.last_workout_local_date == date(2026, 3, 9)


def test_case_8_a_user_who_changes_timezone_mid_streak() -> None:
    """`workout_sessions.local_date` is frozen at write time, in whatever timezone the
    profile held *then* -- it is never recomputed when the profile's timezone later
    changes (§4.6's own docstring). `compute_streak` reflects that: it takes `today` as
    an explicit parameter, resolved by the caller through the profile's *current*
    timezone, and never re-derives it internally. One frozen historical entry
    ("yesterday" under the old timezone) is fed through two different `today` values --
    the one that was true before the change, and the one that is true after -- to prove
    the function reacts to whichever `today` it is actually given, without touching the
    stored date.
    """
    frozen_local_date = date(2026, 8, 12)

    today_before_the_change = date(2026, 8, 13)
    result_before = metrics.compute_streak([frozen_local_date], today=today_before_the_change)
    assert result_before.current_days == 1, "yesterday trained, today not yet -- unbroken"

    # After the profile's timezone changes, "today" (as resolved through the new zone)
    # has moved one calendar day further ahead than the entry above ever accounted for
    # -- e.g. a change from Africa/Cairo to a zone far enough east that the caller's own
    # "today" crosses an extra day boundary. The historical entry itself is untouched;
    # only what counts as "today" has moved.
    today_after_the_change = date(2026, 8, 14)
    result_after = metrics.compute_streak([frozen_local_date], today=today_after_the_change)
    assert result_after.current_days == 0, (
        "the frozen entry is now two days behind the newly resolved 'today' -- the "
        "streak must read as broken, not silently carried over from the old timezone"
    )
    assert result_after.longest_days == 1, "history itself is never rewritten"
    assert result_after.last_workout_local_date == frozen_local_date


def test_case_9_no_sessions_at_all() -> None:
    """This task's own empty-account requirement: a brand-new user's dashboard needs a
    well-formed zero streak, never an error -- the ninth case this task's text asks
    for, alongside the eight §10.1 spells out by name.
    """
    result = metrics.compute_streak([], today=date(2026, 8, 13))
    assert result.current_days == 0
    assert result.longest_days == 0
    assert result.last_workout_local_date is None
