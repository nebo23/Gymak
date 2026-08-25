"""§5.3 (POST /program/generate), §5.4 (GET /program), §5.5 (GET /program/days/{day_id}),
P2-FR-002/003/004.

Per this task's own "done when": the integration tests here prove supersede-not-replace
with history intact (test_regenerating_supersedes_the_previous_program_but_keeps_its_history
below), alongside the 409 PROFILE_REQUIRED gate, the days_per_week validation, the beginner
cap surfacing through the HTTP layer, the stale-profile prompt, the active-session block on
regeneration, the audit trail's shape, the rate limit, and the generic-404 philosophy for
both a malformed and an unknown/other-user day id.

The 135-combination sweep over experience/goal/activity/days_per_week already lives in
tests/unit/test_plan_generator.py against the pure function directly; this file is
deliberately not a second copy of that matrix against HTTP -- it proves the wiring
(service, repository, router) around the generator, not the generator's own rules again.

T-24b adds `estimated_minutes` (every day, both POST /program/generate and GET /program) and
`last_performance` (GET /program/days/{day_id} only). The estimated_minutes tests below prove
both code paths independently -- POST /program/generate computes it from the just-generated
plan in memory, GET /program recomputes it from program_repo.list_exercise_load_by_day -- and
are deliberately not another sweep over services.metrics.estimated_session_minutes itself,
which tests/unit/test_metrics.py already owns. The last_performance tests use the real
POST /workouts + .../sets + .../finish endpoints (matching test_dashboard.py's own precedent)
rather than seeding rows directly, since "most recent" here depends on session ordering that
those endpoints alone produce.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.database import set_rls_user
from app.models.audit import AuditLog
from app.models.program import Program, ProgramDay
from app.models.workout import WorkoutSession
from app.services import metrics
from tests.support import JSONDict, json_body

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_PROFILE = "/api/v1/profile"
_GENERATE = "/api/v1/program/generate"
_PROGRAM = "/api/v1/program"
_WORKOUTS = "/api/v1/workouts"
_PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


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


async def _onboard(client: AsyncClient, access_token: str, **overrides: object) -> Response:
    return await client.post(
        _PROFILE, json=_profile_body(**overrides), headers=_auth_headers(access_token)
    )


async def _register_and_onboard(client: AsyncClient, **overrides: object) -> JSONDict:
    registered = await _register(client)
    response = await _onboard(client, registered["access_token"], **overrides)
    assert response.status_code == 201
    return registered


async def _generate(client: AsyncClient, access_token: str, **body: object) -> Response:
    payload = {"days_per_week": 4, **body}
    return await client.post(_GENERATE, json=payload, headers=_auth_headers(access_token))


async def _get_program(client: AsyncClient, access_token: str) -> Response:
    return await client.get(_PROGRAM, headers=_auth_headers(access_token))


async def _get_day(client: AsyncClient, access_token: str, day_id: str) -> Response:
    return await client.get(f"{_PROGRAM}/days/{day_id}", headers=_auth_headers(access_token))


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


async def _log_and_finish_session(
    client: AsyncClient, access_token: str, *, exercise_id: str, reps: int, weight_kg: object
) -> str:
    """One completed session, one non-warm-up set. Returns the session id."""
    started = await _start(client, access_token)
    assert started.status_code == 201
    session_id: str = json_body(started)["session"]["id"]
    assert (
        await _create_set(
            client,
            access_token,
            session_id,
            exercise_id=exercise_id,
            reps=reps,
            weight_kg=weight_kg,
        )
    ).status_code == 201
    assert (await _finish(client, access_token, session_id)).status_code == 200
    return session_id


# --- 409 PROFILE_REQUIRED (spec §5.1) ------------------------------------------------------


async def test_generate_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _generate(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


async def test_get_program_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _get_program(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


async def test_get_program_day_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _get_day(client, registered["access_token"], str(uuid.uuid4()))
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


# --- POST /program/generate: happy path and shape -------------------------------------------


async def test_generate_happy_path_shape(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client, goal="gain", experience_level="intermediate")

    response = await _generate(client, registered["access_token"], days_per_week=4)
    assert response.status_code == 201
    body = json_body(response)
    program = body["program"]
    assert program["days_per_week"] == 4
    assert program["split_type"] == "upper_lower"
    assert program["goal"] == "gain"
    assert program["experience_level"] == "intermediate"
    assert program["generator_version"] == 2
    assert len(program["days"]) == 4
    for day in program["days"]:
        assert set(day) == {
            "id",
            "day_index",
            "label_key",
            "focus_muscles",
            "exercise_count",
            "estimated_minutes",
        }
        assert day["exercise_count"] > 0
        assert day["estimated_minutes"] > 0
    assert body["notes_key"] == []


@pytest.mark.parametrize(
    "days_per_week,expected_split,expected_day_count",
    [
        (2, "full_body", 2),
        (3, "full_body", 3),
        (4, "upper_lower", 4),
        (5, "upper_lower", 5),
        (6, "push_pull_legs", 6),
    ],
)
async def test_generate_split_selection_per_days_per_week(
    client: AsyncClient, days_per_week: int, expected_split: str, expected_day_count: int
) -> None:
    # intermediate/maintain, not advanced/gain: days_per_week=5 combined with a
    # gain-focused prescription is the exact combination that trips the §6.4 ceiling
    # finding documented in tests/unit/test_plan_generator.py's
    # test_days_per_week_five_can_exceed_the_unreviewed_ceiling_for_gain_focused_plans
    # -- this test is about split selection, not that finding, so it avoids it.
    registered = await _register_and_onboard(
        client, experience_level="intermediate", goal="maintain"
    )
    response = await _generate(client, registered["access_token"], days_per_week=days_per_week)
    assert response.status_code == 201
    program = json_body(response)["program"]
    assert program["split_type"] == expected_split
    assert len(program["days"]) == expected_day_count


async def test_beginner_over_four_days_is_capped_with_notes_key(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client, experience_level="beginner")
    response = await _generate(client, registered["access_token"], days_per_week=6)
    assert response.status_code == 201
    body = json_body(response)
    assert len(body["program"]["days"]) == 4
    assert body["program"]["split_type"] == "upper_lower"
    assert body["notes_key"] == ["plan.notes.beginnerCappedDays"]


@pytest.mark.parametrize("bad_days_per_week", [1, 7])
async def test_generate_rejects_days_per_week_out_of_range(
    client: AsyncClient, bad_days_per_week: int
) -> None:
    registered = await _register_and_onboard(client)
    response = await _generate(client, registered["access_token"], days_per_week=bad_days_per_week)
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": "days_per_week", "code": "OUT_OF_RANGE"}]


async def test_generate_is_rate_limited_at_ten_per_hour_per_user(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    for _ in range(10):
        response = await _generate(client, registered["access_token"], days_per_week=3)
        assert response.status_code == 201

    refused = await _generate(client, registered["access_token"], days_per_week=3)
    assert refused.status_code == 429
    body = json_body(refused)
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers


async def test_generate_records_an_audit_row_without_the_exercise_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client, experience_level="advanced", goal="gain")
    user_id = uuid.UUID(registered["user"]["id"])
    response = await _generate(client, registered["access_token"], days_per_week=6)
    assert response.status_code == 201

    # Scoped to this test's own user: audit_log is process-wide and other tests in this
    # module also generate a program.generated row.
    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "program.generated", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    entry = rows[0]
    assert entry.event_metadata == {
        "days_per_week": 6,
        "split_type": "push_pull_legs",
        "generator_version": 2,
    }


# --- GET /program ----------------------------------------------------------------------------


async def test_get_program_before_ever_generating_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _get_program(client, registered["access_token"])
    assert response.status_code == 404
    assert json_body(response)["code"] == "PROGRAM_NOT_FOUND"


async def test_get_program_returns_the_generated_program_with_no_stale_prompt(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client, goal="maintain")
    generated = await _generate(client, registered["access_token"], days_per_week=4)
    generated_program = json_body(generated)["program"]

    response = await _get_program(client, registered["access_token"])
    assert response.status_code == 200
    body = json_body(response)
    assert body["program"]["id"] == generated_program["id"]
    assert body["stale"] is None


async def test_get_program_reports_stale_when_goal_diverges(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client, goal="gain")
    await _generate(client, registered["access_token"], days_per_week=4)

    patch_response = await client.patch(
        _PROFILE, json={"goal": "maintain"}, headers=_auth_headers(registered["access_token"])
    )
    assert patch_response.status_code == 200

    response = await _get_program(client, registered["access_token"])
    assert response.status_code == 200
    assert json_body(response)["stale"] == {
        "reason": "goal_changed",
        "from": "gain",
        "to": "maintain",
    }


async def test_get_program_estimated_minutes_matches_the_generate_response(
    client: AsyncClient,
) -> None:
    """T-24b: GET /program recomputes `estimated_minutes` via a different code path
    (program_repo.list_exercise_load_by_day, against the persisted rows) than POST
    /program/generate does (straight from the just-generated plan in memory) -- this
    proves the two agree, not just that each is individually non-zero."""
    registered = await _register_and_onboard(client, experience_level="intermediate", goal="gain")
    generated = await _generate(client, registered["access_token"], days_per_week=4)
    generated_days = json_body(generated)["program"]["days"]

    response = await _get_program(client, registered["access_token"])
    assert response.status_code == 200
    fetched_days = json_body(response)["program"]["days"]

    generated_by_id = {day["id"]: day for day in generated_days}
    for fetched_day in fetched_days:
        assert (
            fetched_day["estimated_minutes"]
            == generated_by_id[fetched_day["id"]]["estimated_minutes"]
        )


async def test_estimated_minutes_matches_the_formula_over_each_days_own_rows(
    client: AsyncClient,
) -> None:
    """Every day of a generated program: `estimated_minutes` equals
    services.metrics.estimated_session_minutes fed with that same day's own
    target_sets/rest_seconds -- proven independently for every day, not just the first."""
    registered = await _register_and_onboard(client, experience_level="advanced", goal="gain")
    generated = await _generate(client, registered["access_token"], days_per_week=6)
    days = json_body(generated)["program"]["days"]
    assert len(days) == 6

    for day in days:
        day_detail = await _get_day(client, registered["access_token"], day["id"])
        assert day_detail.status_code == 200
        exercises = json_body(day_detail)["day"]["exercises"]
        expected_minutes = metrics.estimated_session_minutes(
            metrics.ProgramDayLoadInput(
                target_sets=exercise["target_sets"], rest_seconds=exercise["rest_seconds"]
            )
            for exercise in exercises
        )
        assert day["estimated_minutes"] == expected_minutes


# --- GET /program/days/{day_id} ---------------------------------------------------------------


async def test_get_program_day_returns_exercises_in_position_order_with_null_last_performance(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client, experience_level="intermediate", goal="gain")
    generated = await _generate(client, registered["access_token"], days_per_week=4)
    day_summary = json_body(generated)["program"]["days"][0]

    response = await _get_day(client, registered["access_token"], day_summary["id"])
    assert response.status_code == 200
    day = json_body(response)["day"]
    assert day["id"] == day_summary["id"]
    assert day["day_index"] == day_summary["day_index"]
    assert day["label_key"] == day_summary["label_key"]
    assert len(day["exercises"]) == day_summary["exercise_count"]

    positions = [exercise["position"] for exercise in day["exercises"]]
    assert positions == sorted(positions)
    for exercise in day["exercises"]:
        assert exercise["last_performance"] is None
        assert set(exercise) == {
            "id",
            "position",
            "exercise",
            "target_sets",
            "target_reps_min",
            "target_reps_max",
            "rest_seconds",
            "last_performance",
        }
        assert set(exercise["exercise"]) == {"id", "slug", "name", "equipment", "primary_muscle"}


async def test_get_program_day_resolves_name_to_caller_language(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client, language="ar")
    generated = await _generate(client, registered["access_token"], days_per_week=4)
    day_id = json_body(generated)["program"]["days"][0]["id"]

    response = await _get_day(client, registered["access_token"], day_id)
    assert response.status_code == 200
    exercise_name = json_body(response)["day"]["exercises"][0]["exercise"]["name"]
    assert any("؀" <= ch <= "ۿ" for ch in exercise_name), "expected an Arabic name"


async def test_get_program_day_unknown_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _get_day(client, registered["access_token"], str(uuid.uuid4()))
    assert response.status_code == 404
    assert json_body(response)["code"] == "NOT_FOUND"


async def test_get_program_day_malformed_id_returns_404_not_a_validation_error(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    response = await _get_day(client, registered["access_token"], "not-a-uuid")
    assert response.status_code == 404
    assert json_body(response)["code"] == "NOT_FOUND"


async def test_get_program_day_belonging_to_another_user_returns_404(client: AsyncClient) -> None:
    owner = await _register_and_onboard(client, experience_level="intermediate", goal="gain")
    generated = await _generate(client, owner["access_token"], days_per_week=4)
    owners_day_id = json_body(generated)["program"]["days"][0]["id"]

    intruder = await _register_and_onboard(client)
    response = await _get_day(client, intruder["access_token"], owners_day_id)
    assert response.status_code == 404
    assert json_body(response)["code"] == "NOT_FOUND"


# --- last_performance (§5.5) --------------------------------------------------------------


async def test_last_performance_reflects_the_most_recent_completed_session(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    generated = await _generate(client, access_token, days_per_week=4)
    day_id = json_body(generated)["program"]["days"][0]["id"]
    day_detail = await _get_day(client, access_token, day_id)
    exercise_id = json_body(day_detail)["day"]["exercises"][0]["exercise"]["id"]

    older_session_id = await _log_and_finish_session(
        client, access_token, exercise_id=exercise_id, reps=8, weight_kg=60
    )
    newer_session_id = await _log_and_finish_session(
        client, access_token, exercise_id=exercise_id, reps=5, weight_kg=65
    )
    assert older_session_id != newer_session_id

    response = await _get_day(client, access_token, day_id)
    assert response.status_code == 200
    exercise = json_body(response)["day"]["exercises"][0]
    assert exercise["last_performance"]["session_id"] == newer_session_id
    assert exercise["last_performance"]["best_set"] == {"reps": 5, "weight_kg": 65}


async def test_last_performance_ignores_abandoned_and_in_progress_sessions(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    generated = await _generate(client, access_token, days_per_week=4)
    day_id = json_body(generated)["program"]["days"][0]["id"]
    day_detail = await _get_day(client, access_token, day_id)
    exercise_id = json_body(day_detail)["day"]["exercises"][0]["exercise"]["id"]

    completed_session_id = await _log_and_finish_session(
        client, access_token, exercise_id=exercise_id, reps=8, weight_kg=60
    )

    # A more recent abandoned session, with a heavier set -- must never outrank it.
    abandoned = await _start(client, access_token)
    abandoned_id = json_body(abandoned)["session"]["id"]
    assert (
        await _create_set(
            client, access_token, abandoned_id, exercise_id=exercise_id, reps=1, weight_kg=200
        )
    ).status_code == 201
    assert (await _abandon(client, access_token, abandoned_id)).status_code == 200

    response = await _get_day(client, access_token, day_id)
    exercise = json_body(response)["day"]["exercises"][0]
    assert exercise["last_performance"]["session_id"] == completed_session_id

    # An even more recent in-progress session, also with a heavier set -- same rule.
    in_progress = await _start(client, access_token)
    in_progress_id = json_body(in_progress)["session"]["id"]
    assert (
        await _create_set(
            client, access_token, in_progress_id, exercise_id=exercise_id, reps=1, weight_kg=200
        )
    ).status_code == 201

    response = await _get_day(client, access_token, day_id)
    exercise = json_body(response)["day"]["exercises"][0]
    assert exercise["last_performance"]["session_id"] == completed_session_id


async def test_last_performance_best_set_is_never_a_warmup_set(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    generated = await _generate(client, access_token, days_per_week=4)
    day_id = json_body(generated)["program"]["days"][0]["id"]
    day_detail = await _get_day(client, access_token, day_id)
    exercise_id = json_body(day_detail)["day"]["exercises"][0]["exercise"]["id"]

    started = await _start(client, access_token)
    session_id = json_body(started)["session"]["id"]
    # The warm-up is heavier than the real set -- if is_warmup were not excluded, it
    # would win on both raw weight and e1RM.
    assert (
        await _create_set(
            client,
            access_token,
            session_id,
            exercise_id=exercise_id,
            reps=5,
            weight_kg=100,
            is_warmup=True,
        )
    ).status_code == 201
    assert (
        await _create_set(
            client, access_token, session_id, exercise_id=exercise_id, reps=8, weight_kg=60
        )
    ).status_code == 201
    assert (await _finish(client, access_token, session_id)).status_code == 200

    response = await _get_day(client, access_token, day_id)
    exercise = json_body(response)["day"]["exercises"][0]
    assert exercise["last_performance"]["best_set"] == {"reps": 8, "weight_kg": 60}


async def test_last_performance_best_set_picks_the_highest_e1rm_not_the_heaviest_set(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    generated = await _generate(client, access_token, days_per_week=4)
    day_id = json_body(generated)["program"]["days"][0]["id"]
    day_detail = await _get_day(client, access_token, day_id)
    exercise_id = json_body(day_detail)["day"]["exercises"][0]["exercise"]["id"]

    started = await _start(client, access_token)
    session_id = json_body(started)["session"]["id"]
    # Heaviest single set (90kg x 1) vs. highest e1RM (50kg x 30) -- different rows.
    heaviest_e1rm = metrics.estimate_one_rep_max(Decimal("90"), 1)
    highest_e1rm = metrics.estimate_one_rep_max(Decimal("50"), 30)
    assert highest_e1rm > heaviest_e1rm, "the test's own data must make the lighter set win"
    assert (
        await _create_set(
            client, access_token, session_id, exercise_id=exercise_id, reps=1, weight_kg=90
        )
    ).status_code == 201
    assert (
        await _create_set(
            client, access_token, session_id, exercise_id=exercise_id, reps=30, weight_kg=50
        )
    ).status_code == 201
    assert (await _finish(client, access_token, session_id)).status_code == 200

    response = await _get_day(client, access_token, day_id)
    exercise = json_body(response)["day"]["exercises"][0]
    assert exercise["last_performance"]["best_set"] == {"reps": 30, "weight_kg": 50}


async def test_last_performance_never_reflects_another_users_session(client: AsyncClient) -> None:
    intruder = await _register_and_onboard(client)
    intruder_generated = await _generate(client, intruder["access_token"], days_per_week=4)
    intruder_day_id = json_body(intruder_generated)["program"]["days"][0]["id"]
    intruder_day_detail = await _get_day(client, intruder["access_token"], intruder_day_id)
    shared_exercise_id = json_body(intruder_day_detail)["day"]["exercises"][0]["exercise"]["id"]

    owner = await _register_and_onboard(client)
    await _log_and_finish_session(
        client, owner["access_token"], exercise_id=shared_exercise_id, reps=8, weight_kg=60
    )

    response = await _get_day(client, intruder["access_token"], intruder_day_id)
    assert response.status_code == 200
    exercise = json_body(response)["day"]["exercises"][0]
    assert exercise["exercise"]["id"] == shared_exercise_id
    assert exercise["last_performance"] is None


# --- regeneration: supersede, not replace (§4.3), and the active-session block (§5.3) ---------


async def test_regenerating_supersedes_the_previous_program_but_keeps_its_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client, experience_level="intermediate", goal="gain")

    first = await _generate(client, registered["access_token"], days_per_week=4)
    assert first.status_code == 201
    first_program = json_body(first)["program"]
    first_program_id = uuid.UUID(first_program["id"])
    first_day_ids = {uuid.UUID(day["id"]) for day in first_program["days"]}

    second = await _generate(client, registered["access_token"], days_per_week=6)
    assert second.status_code == 201
    second_program = json_body(second)["program"]
    second_program_id = uuid.UUID(second_program["id"])
    assert second_program_id != first_program_id

    # GET /program now returns the new one.
    current = await _get_program(client, registered["access_token"])
    assert json_body(current)["program"]["id"] == str(second_program_id)

    # The old program row is superseded, not gone -- and its days are still there,
    # readable directly (history intact), even though no route surfaces a non-current
    # program's days in this task. programs/program_days are FORCE RLS, so this fresh
    # db_session needs app.user_id bound before either read is visible.
    user_id = uuid.UUID(registered["user"]["id"])
    await set_rls_user(db_session, str(user_id))

    old_program = await db_session.get(Program, first_program_id)
    assert old_program is not None
    assert old_program.is_current is False
    assert old_program.superseded_at is not None

    remaining_day_ids = {
        row.id
        for row in (
            await db_session.execute(
                select(ProgramDay).where(ProgramDay.program_id == first_program_id)
            )
        )
        .scalars()
        .all()
    }
    assert remaining_day_ids == first_day_ids


async def test_regeneration_is_blocked_by_an_active_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    generated = await _generate(client, registered["access_token"], days_per_week=4)
    assert generated.status_code == 201

    user_id = uuid.UUID(registered["user"]["id"])
    await set_rls_user(db_session, str(user_id))
    db_session.add(WorkoutSession(user_id=user_id, status="in_progress", local_date=date.today()))
    await db_session.commit()

    response = await _generate(client, registered["access_token"], days_per_week=5)
    assert response.status_code == 409
    assert json_body(response)["code"] == "SESSION_ACTIVE_BLOCKS_REGENERATION"


# --- Custom exercises must never reach the generator (§6.4 safety, P2-ADR-01) -------------


async def test_a_custom_exercise_never_appears_in_a_generated_plan(client: AsyncClient) -> None:
    """`program_repo.list_available_exercises` filters to `user_id IS NULL`, and this is
    the test that holds it there.

    Not a cosmetic preference. The generator is a pure function of
    `available_exercise_slugs` (P2-ADR-01), and §6.4's per-muscle volume ceilings are
    computed from each row's `primary_muscle`. Those ceilings only mean anything because
    every seeded row's muscle tagging is curated. A user who tags their own movement
    `chest` -- honestly, because that is where they feel it -- would otherwise shift a
    real training-volume limit for themselves. The custom exercise below is deliberately
    tagged `chest` and marked compound, exactly the shape the generator would pick up if
    the filter were ever dropped.
    """
    registered = await _register_and_onboard(client, goal="gain", experience_level="intermediate")
    token = registered["access_token"]

    created = await client.post(
        "/api/v1/exercises",
        json={
            "name": "My Garage Press",
            "primary_muscle": "chest",
            "equipment": "barbell",
            "movement_pattern": "horizontal_push",
            "difficulty": "beginner",
            "is_compound": True,
        },
        headers=_auth_headers(token),
    )
    assert created.status_code == 201, created.text
    custom_id = json_body(created)["exercise"]["id"]

    generated = await _generate(client, token, days_per_week=4)
    assert generated.status_code == 201
    days = json_body(generated)["program"]["days"]
    assert days, "a generated plan with no days would make this test vacuous"

    seen_ids: set[str] = set()
    for day in days:
        detail = await _get_day(client, token, day["id"])
        assert detail.status_code == 200
        exercises = json_body(detail)["day"]["exercises"]
        assert exercises, "an empty day would make this test vacuous"
        seen_ids.update(entry["exercise"]["id"] for entry in exercises)

    assert custom_id not in seen_ids
    # And the exercise really was visible to this user all along -- otherwise its absence
    # from the plan would prove nothing about the generator's filter.
    fetched = await client.get(f"/api/v1/exercises/{custom_id}", headers=_auth_headers(token))
    assert fetched.status_code == 200
    assert json_body(fetched)["exercise"]["is_custom"] is True
