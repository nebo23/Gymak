"""§5.6 (POST /workouts, GET /workouts/active) and §5.8 (POST /workouts/{id}/finish,
POST /workouts/{id}/abandon), P2-FR-005/007, P2-ADR-03. Also covers this task's own
profiles.timezone wiring (§4.2's note names T-18 as the first consumer).

Per this task's own "done when": every transition (start -> finish, start -> abandon)
and every rejected transition (double-start, finish/abandon on a closed session,
finish on an empty session, another user's session) is covered here, along with the
duration case the task calls out explicitly -- a session whose last set was logged at
18:40 but finished the next morning reports its real (18:40-relative) duration, never
`ended_at - started_at`.

POST /workouts/{id}/sets does not exist until T-19, so every test that needs sets on a
session inserts WorkoutSet rows directly via db_session, matching this task's own
instruction ("seed workout_sets directly in the test fixtures").
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.database import set_rls_user
from app.models.exercise import Exercise
from app.models.workout import WorkoutSession, WorkoutSet
from tests.support import JSONDict, json_body

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_PROFILE = "/api/v1/profile"
_WORKOUTS = "/api/v1/workouts"
_ACTIVE = "/api/v1/workouts/active"
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


async def _start(client: AsyncClient, access_token: str, **body: object) -> Response:
    return await client.post(_WORKOUTS, json=body, headers=_auth_headers(access_token))


async def _get_active(client: AsyncClient, access_token: str) -> Response:
    return await client.get(_ACTIVE, headers=_auth_headers(access_token))


async def _finish(
    client: AsyncClient, access_token: str, session_id: str, **body: object
) -> Response:
    return await client.post(
        f"{_WORKOUTS}/{session_id}/finish", json=body, headers=_auth_headers(access_token)
    )


async def _abandon(client: AsyncClient, access_token: str, session_id: str) -> Response:
    return await client.post(
        f"{_WORKOUTS}/{session_id}/abandon", headers=_auth_headers(access_token)
    )


async def _first_exercise_id(db_session: AsyncSession) -> uuid.UUID:
    result = await db_session.execute(select(Exercise.id).limit(1))
    exercise_id = result.scalar_one_or_none()
    assert exercise_id is not None, "the T-16 seed migration must have run"
    return exercise_id


async def _seed_set(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    exercise_id: uuid.UUID,
    set_index: int,
    reps: int,
    weight_kg: str,
    is_warmup: bool = False,
    logged_at: datetime,
) -> None:
    """Seeds one row directly (no POST /workouts/{id}/sets until T-19). Binds RLS
    itself rather than trusting a caller's earlier `set_rls_user` call to still be in
    force: `set_rls_user` is `SET LOCAL`, discarded at the previous statement's
    COMMIT, so a caller seeding a second set -- or one that ran another commit first,
    like `_set_started_at` -- would otherwise insert with no `app.user_id` bound and
    fail RLS on `workout_sets`, not silently insert as the wrong user.
    """
    await set_rls_user(db_session, str(user_id))
    db_session.add(
        WorkoutSet(
            session_id=session_id,
            exercise_id=exercise_id,
            set_index=set_index,
            reps=reps,
            weight_kg=Decimal(weight_kg),
            is_warmup=is_warmup,
            logged_at=logged_at,
        )
    )
    await db_session.commit()


async def _set_started_at(
    db_session: AsyncSession, session_id: uuid.UUID, started_at: datetime
) -> None:
    workout_session = await db_session.get(WorkoutSession, session_id)
    assert workout_session is not None
    workout_session.started_at = started_at
    await db_session.commit()


# --- 409 PROFILE_REQUIRED (spec §5.1) ----------------------------------------------------


async def test_start_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _start(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


async def test_get_active_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _get_active(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


# --- POST /workouts: happy path and shape -------------------------------------------------


async def test_start_creates_an_empty_in_progress_session(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _start(client, registered["access_token"])
    assert response.status_code == 201
    session = json_body(response)["session"]
    assert session["status"] == "in_progress"
    assert session["program_day_id"] is None
    assert session["sets"] == []
    assert set(session) == {"id", "status", "started_at", "local_date", "program_day_id", "sets"}


async def test_start_with_a_program_day_id_records_it_on_the_session(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    generated = await client.post(
        "/api/v1/program/generate",
        json={"days_per_week": 4},
        headers=_auth_headers(registered["access_token"]),
    )
    assert generated.status_code == 201
    day_id = json_body(generated)["program"]["days"][0]["id"]

    response = await _start(client, registered["access_token"], program_day_id=day_id)
    assert response.status_code == 201
    assert json_body(response)["session"]["program_day_id"] == day_id


async def test_start_with_unknown_program_day_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _start(client, registered["access_token"], program_day_id=str(uuid.uuid4()))
    assert response.status_code == 404
    assert json_body(response)["code"] == "NOT_FOUND"


async def test_start_with_malformed_program_day_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _start(client, registered["access_token"], program_day_id="not-a-uuid")
    assert response.status_code == 404
    assert json_body(response)["code"] == "NOT_FOUND"


async def test_start_with_another_users_program_day_id_returns_404(client: AsyncClient) -> None:
    owner = await _register_and_onboard(client)
    generated = await client.post(
        "/api/v1/program/generate",
        json={"days_per_week": 4},
        headers=_auth_headers(owner["access_token"]),
    )
    owners_day_id = json_body(generated)["program"]["days"][0]["id"]

    intruder = await _register_and_onboard(client)
    response = await _start(client, intruder["access_token"], program_day_id=owners_day_id)
    assert response.status_code == 404
    assert json_body(response)["code"] == "NOT_FOUND"


# --- P2-ADR-03: at most one active session -------------------------------------------------


async def test_starting_a_second_session_returns_409_with_the_active_id_in_detail(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    first = await _start(client, registered["access_token"])
    assert first.status_code == 201
    active_id = json_body(first)["session"]["id"]

    second = await _start(client, registered["access_token"])
    assert second.status_code == 409
    body = json_body(second)
    assert body["code"] == "SESSION_ALREADY_ACTIVE"
    assert body["detail"] == active_id


async def test_rate_limit_still_applies_after_a_session_already_active_rejection(
    client: AsyncClient,
) -> None:
    # §7.3: "/workouts (POST) ... 20 / hour ... user" -- every attempt consumes the
    # window, including ones rejected for an unrelated reason (409, not 429).
    registered = await _register_and_onboard(client)
    assert (await _start(client, registered["access_token"])).status_code == 201
    for _ in range(19):
        response = await _start(client, registered["access_token"])
        assert response.status_code == 409

    refused = await _start(client, registered["access_token"])
    assert refused.status_code == 429
    assert json_body(refused)["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers


# --- GET /workouts/active --------------------------------------------------------------------


async def test_get_active_returns_204_when_no_session_is_open(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _get_active(client, registered["access_token"])
    assert response.status_code == 204
    assert response.content == b""


async def test_get_active_returns_the_open_session(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    started = await _start(client, registered["access_token"])
    session_id = json_body(started)["session"]["id"]

    response = await _get_active(client, registered["access_token"])
    assert response.status_code == 200
    assert json_body(response)["session"]["id"] == session_id


# --- §4.2/T-18: profiles.timezone -------------------------------------------------------------


async def test_timezone_defaults_and_is_returned_by_get_profile_and_auth_me(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    headers = _auth_headers(registered["access_token"])

    profile_response = await client.get(_PROFILE, headers=headers)
    assert profile_response.status_code == 200
    assert json_body(profile_response)["profile"]["timezone"] == "Africa/Cairo"

    me_response = await client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 200
    assert json_body(me_response)["profile"]["timezone"] == "Africa/Cairo"


async def test_timezone_is_editable_via_patch_profile(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    headers = _auth_headers(registered["access_token"])

    response = await client.patch(_PROFILE, json={"timezone": "Asia/Tokyo"}, headers=headers)
    assert response.status_code == 200
    assert json_body(response)["profile"]["timezone"] == "Asia/Tokyo"

    confirm = await client.get(_PROFILE, headers=headers)
    assert json_body(confirm)["profile"]["timezone"] == "Asia/Tokyo"


async def test_patch_profile_rejects_an_invalid_timezone(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await client.patch(
        _PROFILE,
        json={"timezone": "Mars/Olympus_Mons"},
        headers=_auth_headers(registered["access_token"]),
    )
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": "timezone", "code": "INVALID"}]


async def test_local_date_is_resolved_through_the_profile_timezone_not_utc(
    client: AsyncClient,
) -> None:
    # UTC+14 -- chosen so the caller's local calendar date is very often a day ahead
    # of UTC's, exercising §4.2's "computed in UTC breaks for every user east of it"
    # failure mode directly rather than merely asserting *some* date comes back.
    extreme_tz = "Pacific/Kiritimati"
    registered = await _register_and_onboard(client)
    patched = await client.patch(
        _PROFILE, json={"timezone": extreme_tz}, headers=_auth_headers(registered["access_token"])
    )
    assert patched.status_code == 200

    before = datetime.now(UTC).astimezone(ZoneInfo(extreme_tz)).date()
    response = await _start(client, registered["access_token"])
    after = datetime.now(UTC).astimezone(ZoneInfo(extreme_tz)).date()
    assert response.status_code == 201

    local_date = date.fromisoformat(json_body(response)["session"]["local_date"])
    assert before <= local_date <= after


# --- POST /workouts/{id}/finish ---------------------------------------------------------------


async def test_finish_on_zero_sets_returns_422_empty_session(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    started = await _start(client, registered["access_token"])
    session_id = json_body(started)["session"]["id"]

    response = await _finish(client, registered["access_token"], session_id)
    assert response.status_code == 422
    assert json_body(response)["code"] == "EMPTY_SESSION"


async def test_finish_computes_duration_from_last_logged_at_not_ended_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # This task's own "done when": last set logged at 18:40, finish called the next
    # morning at (effectively) "now" -- duration must reflect 18:40, never the real
    # finish instant.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    started = await _start(client, registered["access_token"])
    session_id = uuid.UUID(json_body(started)["session"]["id"])

    await set_rls_user(db_session, str(user_id))
    started_at = datetime(2026, 8, 13, 18, 0, tzinfo=UTC)
    await _set_started_at(db_session, session_id, started_at)
    exercise_id = await _first_exercise_id(db_session)
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_id,
        set_index=1,
        reps=8,
        weight_kg="60",
        logged_at=datetime(2026, 8, 13, 18, 40, tzinfo=UTC),
    )

    response = await _finish(client, registered["access_token"], str(session_id))
    assert response.status_code == 200
    session = json_body(response)["session"]
    assert session["status"] == "completed"
    # 40 minutes, from last_logged_at - started_at -- never the real finish instant,
    # which (being "now") is long after 2026-08-13T18:40Z.
    assert session["duration_seconds"] == 40 * 60


async def test_finish_computes_volume_over_non_warmup_sets_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    started = await _start(client, registered["access_token"])
    session_id = uuid.UUID(json_body(started)["session"]["id"])

    await set_rls_user(db_session, str(user_id))
    exercise_id = await _first_exercise_id(db_session)
    now = datetime.now(UTC)
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_id,
        set_index=1,
        reps=10,
        weight_kg="20",
        is_warmup=True,
        logged_at=now,
    )
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_id,
        set_index=2,
        reps=8,
        weight_kg="60",
        logged_at=now,
    )

    response = await _finish(client, registered["access_token"], str(session_id))
    assert response.status_code == 200
    session = json_body(response)["session"]
    # Only the non-warmup set (60kg x 8 = 480) counts; the warmup (20kg x 10) does not.
    assert session["total_volume_kg"] == 480
    assert session["set_count"] == 2
    assert session["exercise_count"] == 1
    assert json_body(response)["records_set"] == []


async def test_finish_on_unknown_session_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _finish(client, registered["access_token"], str(uuid.uuid4()))
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_finish_on_malformed_session_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _finish(client, registered["access_token"], "not-a-uuid")
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_finish_on_another_users_session_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _register_and_onboard(client)
    owner_id = uuid.UUID(owner["user"]["id"])
    started = await _start(client, owner["access_token"])
    session_id = json_body(started)["session"]["id"]

    await set_rls_user(db_session, str(owner_id))
    exercise_id = await _first_exercise_id(db_session)
    await _seed_set(
        db_session,
        user_id=owner_id,
        session_id=uuid.UUID(session_id),
        exercise_id=exercise_id,
        set_index=1,
        reps=5,
        weight_kg="40",
        logged_at=datetime.now(UTC),
    )

    intruder = await _register_and_onboard(client)
    response = await _finish(client, intruder["access_token"], session_id)
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_finish_a_second_time_returns_409_session_not_active(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    started = await _start(client, registered["access_token"])
    session_id = json_body(started)["session"]["id"]

    await set_rls_user(db_session, str(user_id))
    exercise_id = await _first_exercise_id(db_session)
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=uuid.UUID(session_id),
        exercise_id=exercise_id,
        set_index=1,
        reps=5,
        weight_kg="40",
        logged_at=datetime.now(UTC),
    )

    first = await _finish(client, registered["access_token"], session_id)
    assert first.status_code == 200

    second = await _finish(client, registered["access_token"], session_id)
    assert second.status_code == 409
    assert json_body(second)["code"] == "SESSION_NOT_ACTIVE"


# --- POST /workouts/{id}/abandon --------------------------------------------------------------


async def test_abandon_on_another_users_session_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _register_and_onboard(client)
    owner_id = uuid.UUID(owner["user"]["id"])
    started = await _start(client, owner["access_token"])
    session_id = json_body(started)["session"]["id"]

    await set_rls_user(db_session, str(owner_id))
    exercise_id = await _first_exercise_id(db_session)
    await _seed_set(
        db_session,
        user_id=owner_id,
        session_id=uuid.UUID(session_id),
        exercise_id=exercise_id,
        set_index=1,
        reps=5,
        weight_kg="40",
        logged_at=datetime.now(UTC),
    )

    intruder = await _register_and_onboard(client)
    response = await _abandon(client, intruder["access_token"], session_id)
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_abandon_keeps_sets_but_computes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    started = await _start(client, registered["access_token"])
    session_id = uuid.UUID(json_body(started)["session"]["id"])

    await set_rls_user(db_session, str(user_id))
    exercise_id = await _first_exercise_id(db_session)
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_id,
        set_index=1,
        reps=5,
        weight_kg="40",
        logged_at=datetime.now(UTC),
    )

    response = await _abandon(client, registered["access_token"], str(session_id))
    assert response.status_code == 200
    session = json_body(response)["session"]
    assert session["status"] == "abandoned"
    assert session["duration_seconds"] is None
    assert session["total_volume_kg"] is None
    assert session["set_count"] == 1

    # The set is untouched -- abandon never deletes.
    await set_rls_user(db_session, str(user_id))
    remaining = (
        (await db_session.execute(select(WorkoutSet).where(WorkoutSet.session_id == session_id)))
        .scalars()
        .all()
    )
    assert len(remaining) == 1


async def test_abandon_an_empty_session_succeeds(client: AsyncClient) -> None:
    # Unlike finish, abandon has no EMPTY_SESSION guard (§5.8 states it only for
    # finish) -- an empty session is a legitimate thing to walk away from.
    registered = await _register_and_onboard(client)
    started = await _start(client, registered["access_token"])
    session_id = json_body(started)["session"]["id"]

    response = await _abandon(client, registered["access_token"], session_id)
    assert response.status_code == 200
    assert json_body(response)["session"]["status"] == "abandoned"


async def test_abandon_on_unknown_session_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _abandon(client, registered["access_token"], str(uuid.uuid4()))
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_abandon_an_already_finished_session_returns_409(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    started = await _start(client, registered["access_token"])
    session_id = json_body(started)["session"]["id"]

    first = await _abandon(client, registered["access_token"], session_id)
    assert first.status_code == 200

    second = await _abandon(client, registered["access_token"], session_id)
    assert second.status_code == 409
    assert json_body(second)["code"] == "SESSION_NOT_ACTIVE"


async def test_a_new_session_can_be_started_after_abandoning_the_previous_one(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    started = await _start(client, registered["access_token"])
    session_id = json_body(started)["session"]["id"]
    assert (await _abandon(client, registered["access_token"], session_id)).status_code == 200

    response = await _start(client, registered["access_token"])
    assert response.status_code == 201
    assert json_body(response)["session"]["id"] != session_id
