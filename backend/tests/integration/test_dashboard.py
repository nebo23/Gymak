"""§5.11 (GET /records) and §5.12 (GET /dashboard), P2-FR-011/012, P2-ADR-05/07.

This task's own "done when" drives the two heaviest sections below: the brand-new
account's dashboard asserts its *exact* well-formed empty shape (never a 404), and
the streak's end-to-end wiring through the real endpoint -- the arithmetic itself is
exhaustively covered by tests/unit/test_streak.py's nine cases, so this file proves
only that GET /dashboard actually calls it with the right inputs.

No API in this task's scope can backdate a session to an earlier calendar day (POST
/workouts/{id}/finish always uses "now"), so every test that needs sessions on
specific past dates seeds `workout_sessions` rows directly via db_session, matching
test_workout_sessions.py's and test_workout_sets.py's own precedent ("seed directly
... no endpoint exists to produce this shape").
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.database import set_rls_user
from app.models.workout import WorkoutSession, WorkoutSet
from app.services import metrics
from tests.support import JSONDict, json_body

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_PROFILE = "/api/v1/profile"
_EXERCISES = "/api/v1/exercises"
_GENERATE = "/api/v1/program/generate"
_PROGRAM_DAYS = "/api/v1/program/days"
_WORKOUTS = "/api/v1/workouts"
_DASHBOARD = "/api/v1/dashboard"
_RECORDS = "/api/v1/records"
_BODY_WEIGHT = "/api/v1/body-weight"
_PASSWORD = "correct horse battery"
_TZ = "Africa/Cairo"  # profiles.timezone's own default (§4.2)


@pytest.fixture(autouse=True)
def _isolated_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


def _today_local() -> date:
    return datetime.now(UTC).astimezone(ZoneInfo(_TZ)).date()


def _local_week_start() -> date:
    today = _today_local()
    return today - timedelta(days=today.weekday())  # Monday, ISO 8601


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _birth_date_years_ago(years: int) -> str:
    today = date.today()
    try:
        return today.replace(year=today.year - years).isoformat()
    except ValueError:
        return today.replace(year=today.year - years, day=28).isoformat()


async def _register(client: AsyncClient) -> JSONDict:
    response = await client.post(_REGISTER, json={"email": _unique_email(), "password": _PASSWORD})
    assert response.status_code == 201
    return json_body(response)


def _profile_body(**overrides: object) -> JSONDict:
    body: dict[str, object] = {
        "name": "Nabil",
        "gender": "male",
        "birth_date": "1995-01-01",
        "height_cm": 178,
        "weight_kg": 74.5,
        "goal": "maintain",
        "experience_level": "beginner",
        "activity_level": "moderate",
        "unit_system": "metric",
        "language": "ar",
    }
    body.update(overrides)
    return body


async def _register_and_onboard(client: AsyncClient, **overrides: object) -> JSONDict:
    registered = await _register(client)
    response = await client.post(
        _PROFILE, json=_profile_body(**overrides), headers=_auth_headers(registered["access_token"])
    )
    assert response.status_code == 201
    return registered


async def _get_dashboard(client: AsyncClient, access_token: str) -> Response:
    return await client.get(_DASHBOARD, headers=_auth_headers(access_token))


async def _get_records(client: AsyncClient, access_token: str, **params: str) -> Response:
    return await client.get(_RECORDS, params=params, headers=_auth_headers(access_token))


async def _generate_program(client: AsyncClient, access_token: str, days_per_week: int) -> JSONDict:
    response = await client.post(
        _GENERATE, json={"days_per_week": days_per_week}, headers=_auth_headers(access_token)
    )
    assert response.status_code == 201
    return json_body(response)


async def _get_program_day(client: AsyncClient, access_token: str, day_id: str) -> JSONDict:
    response = await client.get(f"{_PROGRAM_DAYS}/{day_id}", headers=_auth_headers(access_token))
    assert response.status_code == 200
    return json_body(response)


async def _exercise_ids(client: AsyncClient, access_token: str, count: int = 2) -> list[str]:
    response = await client.get(
        _EXERCISES, params={"limit": count}, headers=_auth_headers(access_token)
    )
    assert response.status_code == 200
    items = json_body(response)["items"]
    assert len(items) >= count, "the T-16 seed migration must have run with enough exercises"
    return [item["id"] for item in items[:count]]


async def _start(client: AsyncClient, access_token: str, **body: object) -> Response:
    return await client.post(_WORKOUTS, json=body, headers=_auth_headers(access_token))


async def _create_set(
    client: AsyncClient, access_token: str, session_id: str, **body: object
) -> Response:
    return await client.post(
        f"{_WORKOUTS}/{session_id}/sets", json=body, headers=_auth_headers(access_token)
    )


async def _finish(client: AsyncClient, access_token: str, session_id: str) -> Response:
    return await client.post(
        f"{_WORKOUTS}/{session_id}/finish", json={}, headers=_auth_headers(access_token)
    )


async def _abandon(client: AsyncClient, access_token: str, session_id: str) -> Response:
    return await client.post(
        f"{_WORKOUTS}/{session_id}/abandon", headers=_auth_headers(access_token)
    )


async def _put_weight(
    client: AsyncClient, access_token: str, *, measured_on: str, weight_kg: object
) -> Response:
    body: JSONDict = {"measured_on": measured_on, "weight_kg": weight_kg}
    return await client.put(_BODY_WEIGHT, json=body, headers=_auth_headers(access_token))


async def _seed_completed_session(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    local_date: date,
    program_day_id: str | None = None,
    started_at: datetime | None = None,
) -> uuid.UUID:
    """No endpoint in this task's (or T-18's) scope can backdate a session's
    `local_date` -- POST /workouts/{id}/finish always uses "now" -- so every test
    below that needs a completed session on a specific past calendar day seeds one
    directly, matching test_workout_sessions.py's own precedent for exactly this gap.
    """
    await set_rls_user(db_session, str(user_id))
    resolved_started_at = started_at or datetime.combine(
        local_date, datetime.min.time(), tzinfo=UTC
    )
    workout_session = WorkoutSession(
        user_id=user_id,
        program_day_id=uuid.UUID(program_day_id) if program_day_id is not None else None,
        status="completed",
        started_at=resolved_started_at,
        ended_at=resolved_started_at,
        local_date=local_date,
    )
    db_session.add(workout_session)
    await db_session.commit()
    return workout_session.id


async def _seed_set(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    exercise_id: str,
    set_index: int,
    reps: int,
    weight_kg: str,
    is_warmup: bool = False,
) -> None:
    """Same RLS-rebinding precedent as test_workout_sessions.py's own `_seed_set`:
    `set_rls_user` is `SET LOCAL`, discarded at the previous statement's COMMIT, so
    each direct insert rebinds it rather than trusting an earlier call still holds."""
    await set_rls_user(db_session, str(user_id))
    db_session.add(
        WorkoutSet(
            session_id=session_id,
            exercise_id=uuid.UUID(exercise_id),
            set_index=set_index,
            reps=reps,
            weight_kg=Decimal(weight_kg),
            is_warmup=is_warmup,
        )
    )
    await db_session.commit()


# --- 409 PROFILE_REQUIRED (spec §5.1) ----------------------------------------------------


async def test_dashboard_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _get_dashboard(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


async def test_records_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _get_records(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


# --- The empty-account shape: this task's own "done when" ---------------------------------


async def test_dashboard_on_a_brand_new_account_returns_the_well_formed_empty_shape(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client, weight_kg=None)
    response = await _get_dashboard(client, registered["access_token"])
    assert response.status_code == 200
    assert json_body(response) == {
        "greeting_name": "Nabil",
        "active_session": None,
        "next_workout": None,
        "streak": {"current_days": 0, "longest_days": 0, "last_workout_local_date": None},
        "this_week": {
            "completed": 0,
            "target": 0,
            "local_week_start": _local_week_start().isoformat(),
        },
        "weight": {
            "latest_kg": None,
            "measured_on": None,
            "change_30d_kg": None,
            "sparkline": [],
        },
        "recent_records": [],
        "program_stale": None,
        "disclaimer_key": "common.medicalDisclaimer",
    }


async def test_records_on_a_brand_new_account_returns_an_empty_list(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _get_records(client, registered["access_token"])
    assert response.status_code == 200
    assert json_body(response) == {"records": []}


# --- active_session -------------------------------------------------------------------------


async def test_dashboard_reflects_the_active_session(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    started = await _start(client, registered["access_token"])
    assert started.status_code == 201
    session_id = json_body(started)["session"]["id"]

    response = await _get_dashboard(client, registered["access_token"])
    body = json_body(response)
    assert body["active_session"] is not None
    assert body["active_session"]["id"] == session_id
    assert body["active_session"]["status"] == "in_progress"


# --- next_workout: default to day 1, then wrap after the last day (§5.12) -----------------


async def test_dashboard_next_workout_defaults_to_the_first_day_when_never_trained(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    generated = await _generate_program(client, registered["access_token"], days_per_week=3)
    days = generated["program"]["days"]

    response = await _get_dashboard(client, registered["access_token"])
    next_workout = json_body(response)["next_workout"]
    assert next_workout is not None
    assert next_workout["program_day_id"] == days[0]["id"]
    assert next_workout["day_index"] == 1


async def test_dashboard_next_workout_wraps_after_the_last_day_and_estimates_minutes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    generated = await _generate_program(client, registered["access_token"], days_per_week=3)
    days = sorted(generated["program"]["days"], key=lambda d: d["day_index"])
    today = _today_local()

    # Most recently completed against day 3 (the last day) -> wraps back to day 1.
    await _seed_completed_session(
        db_session,
        user_id=user_id,
        local_date=today - timedelta(days=2),
        program_day_id=days[2]["id"],
    )
    wrapped = await _get_dashboard(client, registered["access_token"])
    assert json_body(wrapped)["next_workout"]["day_index"] == 1

    # A more recent completion against day 1 -> next is day 2, not day 1 again.
    await _seed_completed_session(
        db_session,
        user_id=user_id,
        local_date=today - timedelta(days=1),
        program_day_id=days[0]["id"],
    )
    response = await _get_dashboard(client, registered["access_token"])
    next_workout = json_body(response)["next_workout"]
    assert next_workout["program_day_id"] == days[1]["id"]
    assert next_workout["day_index"] == 2

    day_detail = await _get_program_day(client, registered["access_token"], days[1]["id"])
    exercises = day_detail["day"]["exercises"]
    assert next_workout["exercise_count"] == len(exercises)

    expected_minutes = metrics.estimated_session_minutes(
        metrics.ProgramDayLoadInput(
            target_sets=exercise["target_sets"], rest_seconds=exercise["rest_seconds"]
        )
        for exercise in exercises
    )
    assert next_workout["estimated_minutes"] == expected_minutes


# --- streak: end-to-end wiring (arithmetic itself is test_streak.py's job) ----------------


async def test_dashboard_streak_reflects_consecutive_completed_days(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    today = _today_local()

    for offset in (0, 1, 2):
        await _seed_completed_session(
            db_session, user_id=user_id, local_date=today - timedelta(days=offset)
        )

    response = await _get_dashboard(client, registered["access_token"])
    streak = json_body(response)["streak"]
    assert streak["current_days"] == 3
    assert streak["longest_days"] == 3
    assert streak["last_workout_local_date"] == today.isoformat()


async def test_dashboard_streak_ignores_abandoned_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    today = _today_local()

    await set_rls_user(db_session, str(user_id))
    db_session.add(
        WorkoutSession(
            user_id=user_id,
            status="abandoned",
            started_at=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
            ended_at=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
            local_date=today,
        )
    )
    await db_session.commit()

    response = await _get_dashboard(client, registered["access_token"])
    streak = json_body(response)["streak"]
    assert streak == {"current_days": 0, "longest_days": 0, "last_workout_local_date": None}


# --- this_week: only the current local ISO week counts -------------------------------------


async def test_dashboard_this_week_counts_only_the_current_local_week(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    await _generate_program(client, registered["access_token"], days_per_week=4)
    today = _today_local()

    await _seed_completed_session(db_session, user_id=user_id, local_date=today)
    # 8 days back is always outside the current 7-day ISO week, regardless of today's
    # own weekday.
    await _seed_completed_session(db_session, user_id=user_id, local_date=today - timedelta(days=8))

    response = await _get_dashboard(client, registered["access_token"])
    this_week = json_body(response)["this_week"]
    assert this_week == {
        "completed": 1,
        "target": 4,
        "local_week_start": _local_week_start().isoformat(),
    }


# --- weight: sourced from the log, 30-day window, change_30d_kg ---------------------------


async def test_dashboard_weight_block_reflects_the_log_within_the_30_day_window(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client, weight_kg=None)
    today = _today_local()

    assert (
        await _put_weight(
            client,
            registered["access_token"],
            measured_on=(today - timedelta(days=40)).isoformat(),
            weight_kg=90,
        )
    ).status_code == 200
    assert (
        await _put_weight(
            client,
            registered["access_token"],
            measured_on=(today - timedelta(days=10)).isoformat(),
            weight_kg=80,
        )
    ).status_code == 200
    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=today.isoformat(), weight_kg=75
        )
    ).status_code == 200

    response = await _get_dashboard(client, registered["access_token"])
    weight = json_body(response)["weight"]
    assert weight["latest_kg"] == 75
    assert weight["measured_on"] == today.isoformat()
    assert weight["change_30d_kg"] == -5, "the 40-day-old entry is outside the 30-day window"
    dates_in_sparkline = {point["measured_on"] for point in weight["sparkline"]}
    assert dates_in_sparkline == {(today - timedelta(days=10)).isoformat(), today.isoformat()}


# --- P2-SAF-002: a minor's dashboard omits change_30d_kg, keeps the rest ------------------


async def test_dashboard_omits_change_30d_kg_for_a_minor_but_keeps_the_weight_data(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(
        client, birth_date=_birth_date_years_ago(16), weight_kg=None
    )
    today = _today_local()
    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=today.isoformat(), weight_kg=60
        )
    ).status_code == 200

    response = await _get_dashboard(client, registered["access_token"])
    weight = json_body(response)["weight"]
    assert "change_30d_kg" not in weight, (
        "P2-SAF-002: a weight-direction framing key must be physically absent for a minor"
    )
    assert weight["latest_kg"] == 60, "the weight data itself must still be returned"
    assert weight["measured_on"] == today.isoformat()
    assert weight["sparkline"] == [{"measured_on": today.isoformat(), "weight_kg": 60}]


async def test_dashboard_includes_change_30d_kg_for_an_adult(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client, weight_kg=None)
    today = _today_local()
    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=today.isoformat(), weight_kg=75
        )
    ).status_code == 200

    response = await _get_dashboard(client, registered["access_token"])
    weight = json_body(response)["weight"]
    assert "change_30d_kg" in weight
    assert weight["change_30d_kg"] == 0


# --- program_stale reuse (§5.4 comparison, surfaced on the dashboard too) -----------------


async def test_dashboard_program_stale_when_the_profile_goal_has_diverged(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client, goal="maintain")
    await _generate_program(client, registered["access_token"], days_per_week=3)

    patched = await client.patch(
        _PROFILE, json={"goal": "gain"}, headers=_auth_headers(registered["access_token"])
    )
    assert patched.status_code == 200

    response = await _get_dashboard(client, registered["access_token"])
    assert json_body(response)["program_stale"] == {
        "reason": "goal_changed",
        "from": "maintain",
        "to": "gain",
    }


# --- GET /records: excludes warm-ups and non-completed sessions (P2-ADR-05) ---------------


async def test_records_excludes_warmup_sets_and_non_completed_sessions(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    [exercise_id] = await _exercise_ids(client, access_token, count=1)

    # A completed session: one warm-up set (heavier) and one real set.
    completed = await _start(client, access_token)
    completed_id = json_body(completed)["session"]["id"]
    assert (
        await _create_set(
            client,
            access_token,
            completed_id,
            exercise_id=exercise_id,
            reps=10,
            weight_kg=100,
            is_warmup=True,
        )
    ).status_code == 201
    assert (
        await _create_set(
            client, access_token, completed_id, exercise_id=exercise_id, reps=5, weight_kg=50
        )
    ).status_code == 201
    assert (await _finish(client, access_token, completed_id)).status_code == 200

    # An abandoned session with a heavier real set -- must never outrank the above.
    abandoned = await _start(client, access_token)
    abandoned_id = json_body(abandoned)["session"]["id"]
    assert (
        await _create_set(
            client, access_token, abandoned_id, exercise_id=exercise_id, reps=1, weight_kg=200
        )
    ).status_code == 201
    assert (await _abandon(client, access_token, abandoned_id)).status_code == 200

    response = await _get_records(client, access_token)
    body = json_body(response)
    assert len(body["records"]) == 1
    record = body["records"][0]
    assert record["heaviest_set"]["weight_kg"] == 50
    assert record["heaviest_set"]["reps"] == 5
    assert record["total_sets"] == 1


async def test_records_aggregates_heaviest_e1rm_and_best_session_volume(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    [exercise_id] = await _exercise_ids(client, access_token, count=1)

    session_a = await _start(client, access_token)
    session_a_id = json_body(session_a)["session"]["id"]
    assert (
        await _create_set(
            client, access_token, session_a_id, exercise_id=exercise_id, reps=8, weight_kg=60
        )
    ).status_code == 201
    assert (await _finish(client, access_token, session_a_id)).status_code == 200

    session_b = await _start(client, access_token)
    session_b_id = json_body(session_b)["session"]["id"]
    assert (
        await _create_set(
            client,
            access_token,
            session_b_id,
            exercise_id=exercise_id,
            reps=10,
            weight_kg=20,
            is_warmup=True,
        )
    ).status_code == 201
    assert (
        await _create_set(
            client, access_token, session_b_id, exercise_id=exercise_id, reps=5, weight_kg=70
        )
    ).status_code == 201
    assert (await _finish(client, access_token, session_b_id)).status_code == 200

    response = await _get_records(client, access_token)
    record = json_body(response)["records"][0]

    expected_e1rm_a = metrics.estimate_one_rep_max(Decimal("60"), 8)
    expected_e1rm_b = metrics.estimate_one_rep_max(Decimal("70"), 5)
    assert expected_e1rm_b > expected_e1rm_a, "the test's own data must make session B win"

    assert record["heaviest_set"]["weight_kg"] == 70
    assert record["best_e1rm"]["value_kg"] == float(expected_e1rm_b)
    assert record["best_e1rm"]["weight_kg"] == 70
    assert record["best_e1rm"]["reps"] == 5
    # Session A's volume (480) beats session B's non-warmup volume (350).
    assert record["best_session_volume"]["volume_kg"] == 480
    assert record["best_session_volume"]["session_id"] == session_a_id
    assert record["total_sets"] == 2, "the warm-up set in session B must not be counted"


async def test_records_filtered_by_exercise_id_and_omits_unperformed_exercises(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    exercise_a, exercise_b = await _exercise_ids(client, access_token, count=2)

    for exercise_id in (exercise_a, exercise_b):
        session = await _start(client, access_token)
        session_id = json_body(session)["session"]["id"]
        assert (
            await _create_set(
                client, access_token, session_id, exercise_id=exercise_id, reps=5, weight_kg=40
            )
        ).status_code == 201
        assert (await _finish(client, access_token, session_id)).status_code == 200

    unfiltered = await _get_records(client, access_token)
    assert len(json_body(unfiltered)["records"]) == 2, (
        "only the exercises actually performed may appear -- never the whole library"
    )

    filtered = await _get_records(client, access_token, exercise_id=exercise_a)
    records = json_body(filtered)["records"]
    assert len(records) == 1
    assert records[0]["exercise"]["id"] == exercise_a


async def test_records_with_a_malformed_exercise_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _get_records(client, registered["access_token"], exercise_id="not-a-uuid")
    assert response.status_code == 404
    assert json_body(response)["code"] == "EXERCISE_NOT_FOUND"


async def test_records_with_an_unknown_exercise_id_returns_an_empty_list(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    response = await _get_records(client, registered["access_token"], exercise_id=str(uuid.uuid4()))
    assert response.status_code == 200
    assert json_body(response) == {"records": []}


async def test_dashboard_recent_records_reports_the_best_e1rm(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    [exercise_id] = await _exercise_ids(client, access_token, count=1)

    session = await _start(client, access_token)
    session_id = json_body(session)["session"]["id"]
    assert (
        await _create_set(
            client, access_token, session_id, exercise_id=exercise_id, reps=8, weight_kg=60
        )
    ).status_code == 201
    assert (await _finish(client, access_token, session_id)).status_code == 200

    response = await _get_dashboard(client, access_token)
    recent_records = json_body(response)["recent_records"]
    assert len(recent_records) == 1
    assert recent_records[0]["kind"] == "e1rm"
    assert recent_records[0]["value"] == float(metrics.estimate_one_rep_max(Decimal("60"), 8))
    assert recent_records[0]["local_date"] == _today_local().isoformat()


# --- Cross-tenant isolation ------------------------------------------------------------------


async def test_records_never_returns_another_users_sets(client: AsyncClient) -> None:
    owner = await _register_and_onboard(client)
    [exercise_id] = await _exercise_ids(client, owner["access_token"], count=1)
    session = await _start(client, owner["access_token"])
    session_id = json_body(session)["session"]["id"]
    assert (
        await _create_set(
            client, owner["access_token"], session_id, exercise_id=exercise_id, reps=5, weight_kg=50
        )
    ).status_code == 201
    assert (await _finish(client, owner["access_token"], session_id)).status_code == 200

    intruder = await _register_and_onboard(client)
    response = await _get_records(client, intruder["access_token"])
    assert json_body(response) == {"records": []}


async def test_dashboard_never_reflects_another_users_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _register_and_onboard(client)
    owner_id = uuid.UUID(owner["user"]["id"])
    await _seed_completed_session(db_session, user_id=owner_id, local_date=_today_local())
    assert (await _start(client, owner["access_token"])).status_code == 201

    intruder = await _register_and_onboard(client)
    response = await _get_dashboard(client, intruder["access_token"])
    body = json_body(response)
    assert body["active_session"] is None
    assert body["streak"] == {"current_days": 0, "longest_days": 0, "last_workout_local_date": None}


# --- Rate limit: 120 / hour per user, GET /dashboard only (§7.3) --------------------------


async def test_dashboard_rate_limit_applies_at_120_per_hour(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)

    for _ in range(120):
        response = await _get_dashboard(client, registered["access_token"])
        assert response.status_code == 200

    refused = await _get_dashboard(client, registered["access_token"])
    assert refused.status_code == 429
    assert json_body(refused)["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers
