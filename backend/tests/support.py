"""Shared typing helper for integration tests (A.5 item 17).

httpx's ``Response.json()`` is typed ``Any``, so five integration test files had each
independently re-implemented an "assert status, then parse" helper with a bare ``dict``
return annotation -- the exact ``type-arg`` / ``no-any-return`` pattern ``mypy --strict``
flags. One helper, used everywhere, means the fix lives in one place instead of five.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.models.body_weight import BodyWeightEntry
from app.models.workout import WorkoutSession, WorkoutSet

JSONDict = dict[str, Any]


def json_body(response: Response) -> JSONDict:
    body: JSONDict = response.json()
    return body


# §11.1's log-capture test needs every line the WHOLE suite printed, accumulated by an
# autouse fixture in conftest.py. It lives here, not in conftest.py itself, because
# pytest's own conftest-loading mechanism imports that file under the bare module name
# "conftest" (confirmed empirically: `sys.modules` holds both "conftest" and
# "tests.conftest" as two DISTINCT module objects when anything does `from
# tests.conftest import x`), so a list defined there and a list imported via
# `tests.conftest` from elsewhere are two different objects -- the fixture would
# faithfully fill one while every test read the other, which stayed empty forever.
# tests/support.py has no such special-cased loading path, so `tests.support` resolves
# to exactly one module everywhere it is imported, and this list is genuinely shared.
ALL_CAPTURED_OUTPUT: list[str] = []


# =========================================================================================
# T-22: the seeded-load helper for spec 10.1's performance row -- "a seeded account with
# 12 months of sessions (~150 sessions, ~2,700 sets) and 365 weight entries. The seed
# helper is committed, so the number is reproducible rather than anecdotal."
# =========================================================================================


async def seed_workout_history(
    session: AsyncSession,
    user_id: uuid.UUID,
    exercise_ids: list[uuid.UUID],
    *,
    session_count: int = 150,
    sets_per_session: int = 18,
    weight_entry_count: int = 365,
) -> None:
    """Writes ~150 completed sessions (~2,700 sets total) spread over the past 365
    days, plus one body-weight entry per of the past `weight_entry_count` days,
    directly via the ORM -- not through the API. Going through
    POST /workouts + POST .../sets for 2,700 sets would multiply this into thousands
    of HTTP round trips and run straight into workouts.sets' own 300/hour rate limit
    (spec 5.7); this is the "committed seed helper" the performance row asks for
    instead, matching how tests/security/test_rls.py already seeds Phase 2 rows
    directly for the same reason (large volume, not exercising the service layer).

    The caller must bind `app.user_id` to `user_id` (`app.database.set_rls_user`) on
    `session` before calling this -- every table written here (`workout_sessions`,
    `workout_sets`, `body_weight_entries`) is FORCE-RLS with an owner policy (P2-ADR-09,
    spec 4.10), so an unbound or wrongly-bound `app.user_id` fails every INSERT's
    WITH CHECK rather than silently seeding the wrong user. The caller also commits --
    this function only adds and flushes, matching every other repository-adjacent
    helper in this codebase's own convention of never committing on the caller's behalf.

    `sets_per_session` is split three exercises deep (matching a plan day's typical
    shape, spec 6.3) so `sets_per_session` must be a multiple of 3; the default 18
    gives exactly 2,700 sets over 150 sessions, matching the spec's own numbers.
    """
    if sets_per_session % 3 != 0:
        raise ValueError("sets_per_session must be a multiple of 3")
    exercises_per_session = 3
    sets_per_exercise = sets_per_session // exercises_per_session
    if not exercise_ids:
        raise ValueError("exercise_ids must be non-empty")

    today = date.today()
    span_days = 365
    # Evenly spread across the year rather than clustered at one end -- so
    # `ix_sessions_user_local_date` and the streak/records queries see a realistic
    # scatter of local_date values, not 150 rows all sharing a handful of dates.
    step = span_days / session_count

    rows: list[WorkoutSession | WorkoutSet | BodyWeightEntry] = []
    for i in range(session_count):
        offset_days = int(i * step)
        local_date = today - timedelta(days=span_days - offset_days)
        started_at = datetime.combine(local_date, time(18, 0), tzinfo=UTC)
        ended_at = started_at + timedelta(minutes=50)

        session_id = new_id()
        total_volume = Decimal("0")
        for slot in range(exercises_per_session):
            exercise_id = exercise_ids[(i + slot) % len(exercise_ids)]
            for set_index in range(1, sets_per_exercise + 1):
                reps = 8
                weight_kg = Decimal("60.00") + Decimal(set_index)
                rows.append(
                    WorkoutSet(
                        id=new_id(),
                        session_id=session_id,
                        exercise_id=exercise_id,
                        set_index=set_index,
                        reps=reps,
                        weight_kg=weight_kg,
                        is_warmup=False,
                        logged_at=started_at,
                    )
                )
                total_volume += weight_kg * reps

        rows.append(
            WorkoutSession(
                id=session_id,
                user_id=user_id,
                program_day_id=None,
                status="completed",
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=3000,
                total_volume_kg=total_volume,
                local_date=local_date,
            )
        )

    for day_offset in range(weight_entry_count):
        measured_on = today - timedelta(days=day_offset)
        rows.append(
            BodyWeightEntry(
                id=new_id(),
                user_id=user_id,
                measured_on=measured_on,
                weight_kg=Decimal("75.00") - (Decimal(day_offset % 10) / Decimal(10)),
            )
        )

    session.add_all(rows)
    await session.flush()


def p95(samples: list[float]) -> float:
    """Nearest-rank p95 over `samples`, sorted ascending. Used by
    tests/performance/test_seeded_load.py to check spec P2-NFR-01 ("p95 under 400 ms")
    against a real set of measured request durations -- a dependency-free
    implementation rather than `statistics.quantiles` so the interpolation method is
    explicit and does not depend on a particular Python version's default.
    """
    if not samples:
        raise ValueError("p95 of an empty sample set is undefined")
    ordered = sorted(samples)
    rank = math.ceil(0.95 * len(ordered))
    return ordered[max(rank - 1, 0)]
