"""§5.9 GET /workouts (history) and GET /workouts/{id} (one session in full),
P2-FR-008.

§5.9 is the one endpoint pair §5.1's catalogue names that no task in §12's pack ever
built: T-18 owns the session lifecycle, T-19 the sets, T-21 the records and dashboard,
and none of their file lists reaches these two routes. T-27 (the mobile history screen)
consumes both, so the gap is closed here rather than discovered from the client.

Sets are seeded directly via `db_session` wherever a *finished* session with a known
`logged_at` is needed -- POST /workouts/{id}/sets stamps `logged_at` server-side, and
several tests here depend on controlling it (ordering, first-logged grouping). This
mirrors tests/integration/test_workout_sessions.py's own `_seed_set` for the same
reason.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

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


async def _register_and_onboard(client: AsyncClient, **overrides: object) -> JSONDict:
    registered = await _register(client)
    response = await client.post(
        _PROFILE,
        json=_profile_body(**overrides),
        headers=_auth_headers(registered["access_token"]),
    )
    assert response.status_code == 201
    return registered


async def _history(client: AsyncClient, access_token: str, **params: str | int) -> Response:
    return await client.get(_WORKOUTS, params=params, headers=_auth_headers(access_token))


async def _detail(client: AsyncClient, access_token: str, session_id: str) -> Response:
    return await client.get(f"{_WORKOUTS}/{session_id}", headers=_auth_headers(access_token))


async def _first_exercise_id(db_session: AsyncSession) -> uuid.UUID:
    result = await db_session.execute(select(Exercise.id).order_by(Exercise.slug).limit(1))
    exercise_id = result.scalar_one_or_none()
    assert exercise_id is not None, "the T-16 seed migration must have run"
    return exercise_id


async def _exercise_ids(db_session: AsyncSession, count: int) -> list[uuid.UUID]:
    result = await db_session.execute(select(Exercise.id).order_by(Exercise.slug).limit(count))
    ids = list(result.scalars().all())
    assert len(ids) == count
    return ids


async def _seed_session(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    local_date: date,
    status: str = "completed",
    started_at: datetime | None = None,
    program_day_id: uuid.UUID | None = None,
    duration_seconds: int | None = 1800,
    total_volume_kg: str | None = "1000",
    notes: str | None = None,
) -> uuid.UUID:
    """A finished session written straight to the table. The lifecycle endpoints can
    only ever produce a session whose `local_date` is *today*, so a multi-day history
    -- which is the entire subject of §5.9 -- cannot be built through the API at all.
    """
    await set_rls_user(db_session, str(user_id))
    workout_session = WorkoutSession(
        user_id=user_id,
        program_day_id=program_day_id,
        status=status,
        started_at=started_at or datetime.combine(local_date, datetime.min.time(), tzinfo=UTC),
        ended_at=None if status == "in_progress" else datetime.now(UTC),
        duration_seconds=None if status != "completed" else duration_seconds,
        total_volume_kg=None if status != "completed" else Decimal(total_volume_kg or "0"),
        notes=notes,
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
    exercise_id: uuid.UUID,
    set_index: int,
    reps: int,
    weight_kg: str,
    is_warmup: bool = False,
    logged_at: datetime,
) -> None:
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


# --- 409 PROFILE_REQUIRED (§5.1) ----------------------------------------------------------


async def test_history_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _history(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


async def test_detail_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _detail(client, registered["access_token"], str(uuid.uuid4()))
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


# --- GET /workouts: empty, shape, ordering -------------------------------------------------


async def test_history_on_a_brand_new_account_is_an_empty_page_not_a_404(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    response = await _history(client, registered["access_token"])
    assert response.status_code == 200
    assert json_body(response) == {"items": [], "next_cursor": None}


async def test_history_returns_exactly_the_seven_summary_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # §5.9: "returns summaries only -- id, local_date, status, duration, volume, set
    # count, and the program day's label_key." No `sets` array, no `notes`.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    session_id = await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, 10))
    exercise_id = await _first_exercise_id(db_session)
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_id,
        set_index=1,
        reps=8,
        weight_kg="60",
        logged_at=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
    )

    response = await _history(client, registered["access_token"])
    assert response.status_code == 200
    items = json_body(response)["items"]
    assert len(items) == 1
    assert set(items[0]) == {
        "id",
        "local_date",
        "status",
        "duration_seconds",
        "total_volume_kg",
        "set_count",
        "label_key",
    }
    assert items[0]["local_date"] == "2026-08-10"
    assert items[0]["status"] == "completed"
    assert items[0]["set_count"] == 1
    assert items[0]["label_key"] is None


async def test_history_is_newest_first(client: AsyncClient, db_session: AsyncSession) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    for day in (1, 5, 3):
        await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, day))

    response = await _history(client, registered["access_token"])
    assert response.status_code == 200
    dates = [item["local_date"] for item in json_body(response)["items"]]
    assert dates == ["2026-08-05", "2026-08-03", "2026-08-01"]


async def test_history_counts_warmup_sets_too(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # §5.9 says "set count", unqualified. P2-ADR-04 excludes warm-ups from records and
    # volume, not from existing -- and the detail view shows them (T-27 renders them
    # "visually distinguished"), so a count that hid them would disagree with the
    # screen the count sits above.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    session_id = await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, 10))
    exercise_id = await _first_exercise_id(db_session)
    for index, is_warmup in ((1, True), (2, False)):
        await _seed_set(
            db_session,
            user_id=user_id,
            session_id=session_id,
            exercise_id=exercise_id,
            set_index=index,
            reps=8,
            weight_kg="60",
            is_warmup=is_warmup,
            logged_at=datetime(2026, 8, 10, 18, index, tzinfo=UTC),
        )

    response = await _history(client, registered["access_token"])
    assert json_body(response)["items"][0]["set_count"] == 2


async def test_history_includes_abandoned_and_in_progress_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # The history is the log of what the user did. P2-ADR-04 keeps abandoned sessions
    # out of *records and the streak* -- it does not erase them from their own history.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    await _seed_session(
        db_session, user_id=user_id, local_date=date(2026, 8, 1), status="completed"
    )
    await _seed_session(
        db_session, user_id=user_id, local_date=date(2026, 8, 2), status="abandoned"
    )
    await _seed_session(
        db_session, user_id=user_id, local_date=date(2026, 8, 3), status="in_progress"
    )

    response = await _history(client, registered["access_token"])
    statuses = {item["status"] for item in json_body(response)["items"]}
    assert statuses == {"completed", "abandoned", "in_progress"}


async def test_history_reports_the_program_days_label_key(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    generated = await client.post(
        "/api/v1/program/generate",
        json={"days_per_week": 4},
        headers=_auth_headers(registered["access_token"]),
    )
    assert generated.status_code == 201
    day = json_body(generated)["program"]["days"][0]

    await _seed_session(
        db_session,
        user_id=user_id,
        local_date=date(2026, 8, 10),
        program_day_id=uuid.UUID(day["id"]),
    )

    response = await _history(client, registered["access_token"])
    assert json_body(response)["items"][0]["label_key"] == day["label_key"]


# --- filters ---------------------------------------------------------------------------------


async def test_history_filters_by_from_and_to_inclusively(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    for day in (1, 5, 10, 15):
        await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, day))

    response = await _history(
        client, registered["access_token"], **{"from": "2026-08-05", "to": "2026-08-10"}
    )
    assert response.status_code == 200
    dates = [item["local_date"] for item in json_body(response)["items"]]
    assert dates == ["2026-08-10", "2026-08-05"]


async def test_history_filters_by_status(client: AsyncClient, db_session: AsyncSession) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    await _seed_session(
        db_session, user_id=user_id, local_date=date(2026, 8, 1), status="completed"
    )
    await _seed_session(
        db_session, user_id=user_id, local_date=date(2026, 8, 2), status="abandoned"
    )

    response = await _history(client, registered["access_token"], status="abandoned")
    assert response.status_code == 200
    items = json_body(response)["items"]
    assert len(items) == 1
    assert items[0]["status"] == "abandoned"


async def test_an_unknown_status_filter_is_rejected_not_silently_empty(
    client: AsyncClient,
) -> None:
    # A typo'd filter that returned an empty page would read exactly like a user who
    # has never trained -- the single most misleading thing this endpoint could do.
    registered = await _register_and_onboard(client)
    response = await _history(client, registered["access_token"], status="finished")
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": "status", "code": "INVALID"}]


# --- cursor pagination -------------------------------------------------------------------------


async def test_history_pages_through_every_session_without_repeat_or_gap(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    for day in range(1, 11):
        await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, day))

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # generous bound; the loop breaks on next_cursor = None
        params: dict[str, str | int] = {"limit": 3}
        if cursor is not None:
            params["cursor"] = cursor
        response = await _history(client, registered["access_token"], **params)
        assert response.status_code == 200
        body = json_body(response)
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert cursor is None
    assert len(seen) == 10
    assert len(set(seen)) == 10, "a page boundary repeated a row"


async def test_two_sessions_on_the_same_local_date_still_page_cleanly(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # The reason the cursor carries (local_date, started_at, id) and not local_date
    # alone: a keyset on a non-unique column drops or repeats rows at the boundary.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    same_day = date(2026, 8, 10)
    for hour in (8, 12, 18):
        await _seed_session(
            db_session,
            user_id=user_id,
            local_date=same_day,
            started_at=datetime(2026, 8, 10, hour, tzinfo=UTC),
        )

    first = await _history(client, registered["access_token"], limit=2)
    first_body = json_body(first)
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"] is not None

    second = await _history(
        client, registered["access_token"], limit=2, cursor=first_body["next_cursor"]
    )
    second_body = json_body(second)
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None

    ids = [item["id"] for item in first_body["items"] + second_body["items"]]
    assert len(set(ids)) == 3


async def test_a_forged_cursor_is_a_validation_error(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _history(client, registered["access_token"], cursor="not-a-real-cursor")
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": "cursor", "code": "INVALID"}]


# --- cross-tenant ------------------------------------------------------------------------------


async def test_history_never_shows_another_users_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _register_and_onboard(client)
    owner_id = uuid.UUID(owner["user"]["id"])
    await _seed_session(db_session, user_id=owner_id, local_date=date(2026, 8, 10))

    intruder = await _register_and_onboard(client)
    response = await _history(client, intruder["access_token"])
    assert response.status_code == 200
    assert json_body(response)["items"] == []


async def test_detail_of_another_users_session_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _register_and_onboard(client)
    owner_id = uuid.UUID(owner["user"]["id"])
    session_id = await _seed_session(db_session, user_id=owner_id, local_date=date(2026, 8, 10))

    intruder = await _register_and_onboard(client)
    response = await _detail(client, intruder["access_token"], str(session_id))
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_detail_never_leaks_another_users_notes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # §11.1's security matrix: "no endpoint returns another user's notes." This is the
    # only Phase 2 endpoint that returns a session's notes at all, so the assertion
    # belongs here rather than only in the generic cross-tenant sweep.
    secret = "my private training note"
    owner = await _register_and_onboard(client)
    owner_id = uuid.UUID(owner["user"]["id"])
    session_id = await _seed_session(
        db_session, user_id=owner_id, local_date=date(2026, 8, 10), notes=secret
    )

    intruder = await _register_and_onboard(client)
    response = await _detail(client, intruder["access_token"], str(session_id))
    assert response.status_code == 404
    assert secret not in response.text


# --- GET /workouts/{id} -------------------------------------------------------------------------


async def test_detail_on_unknown_session_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _detail(client, registered["access_token"], str(uuid.uuid4()))
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_detail_on_malformed_session_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _detail(client, registered["access_token"], "not-a-uuid")
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_active_still_resolves_and_is_not_swallowed_by_the_id_route(
    client: AsyncClient,
) -> None:
    # `/workouts/active` is a literal path declared before `/workouts/{id}`. If that
    # order ever inverts, this returns 404 SESSION_NOT_FOUND instead of 204.
    registered = await _register_and_onboard(client)
    response = await client.get(
        f"{_WORKOUTS}/active", headers=_auth_headers(registered["access_token"])
    )
    assert response.status_code == 204


async def test_detail_carries_each_sets_derived_block(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    session_id = await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, 10))
    exercise_id = await _first_exercise_id(db_session)
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_id,
        set_index=1,
        reps=8,
        weight_kg="60",
        logged_at=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
    )

    response = await _detail(client, registered["access_token"], str(session_id))
    assert response.status_code == 200
    session = json_body(response)["session"]
    assert session["set_count"] == 1
    assert session["exercise_count"] == 1
    only_set = session["exercises"][0]["sets"][0]
    # §5.7's own worked example: 60kg x 8 -> volume 480, e1RM 76.
    assert only_set["derived"] == {"volume_kg": 480, "e1rm_kg": 76}


async def test_detail_of_an_ad_hoc_session_groups_in_first_logged_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # §5.9: "in first-logged order for an empty one" -- a session with no program day
    # behind it. Exercise B is logged first, so it leads, even though A sorts earlier
    # by slug and would win any incidental database ordering.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    session_id = await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, 10))
    exercise_a, exercise_b = await _exercise_ids(db_session, 2)

    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_b,
        set_index=1,
        reps=8,
        weight_kg="60",
        logged_at=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
    )
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_a,
        set_index=1,
        reps=8,
        weight_kg="40",
        logged_at=datetime(2026, 8, 10, 18, 30, tzinfo=UTC),
    )

    response = await _detail(client, registered["access_token"], str(session_id))
    assert response.status_code == 200
    groups = json_body(response)["session"]["exercises"]
    assert [group["exercise"]["id"] for group in groups] == [str(exercise_b), str(exercise_a)]


async def test_detail_of_a_plan_backed_session_groups_in_position_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # §5.9: "grouped by exercise in `position` order for a plan-backed session." The
    # sets are logged in reverse plan order on purpose, so first-logged order and
    # position order disagree and only the correct one passes.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    generated = await client.post(
        "/api/v1/program/generate",
        json={"days_per_week": 4},
        headers=_auth_headers(registered["access_token"]),
    )
    assert generated.status_code == 201
    day_id = json_body(generated)["program"]["days"][0]["id"]

    day_detail = await client.get(
        f"/api/v1/program/days/{day_id}", headers=_auth_headers(registered["access_token"])
    )
    assert day_detail.status_code == 200
    planned = json_body(day_detail)["day"]["exercises"]
    assert len(planned) >= 2
    first_planned = planned[0]["exercise"]["id"]
    second_planned = planned[1]["exercise"]["id"]

    session_id = await _seed_session(
        db_session,
        user_id=user_id,
        local_date=date(2026, 8, 10),
        program_day_id=uuid.UUID(day_id),
    )
    # Logged second-planned first, so first-logged order is the *wrong* answer.
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=uuid.UUID(second_planned),
        set_index=1,
        reps=8,
        weight_kg="40",
        logged_at=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
    )
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=uuid.UUID(first_planned),
        set_index=1,
        reps=8,
        weight_kg="60",
        logged_at=datetime(2026, 8, 10, 18, 30, tzinfo=UTC),
    )

    response = await _detail(client, registered["access_token"], str(session_id))
    assert response.status_code == 200
    groups = json_body(response)["session"]["exercises"]
    assert [group["exercise"]["id"] for group in groups] == [first_planned, second_planned]


async def test_an_exercise_the_plan_never_prescribed_sorts_after_the_ones_it_did(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # A user who swaps a movement in mid-session: it has no `position`, so it cannot
    # be interleaved into the plan's order, and appending it is the only ordering that
    # keeps the planned exercises in the sequence the plan actually specified.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    generated = await client.post(
        "/api/v1/program/generate",
        json={"days_per_week": 4},
        headers=_auth_headers(registered["access_token"]),
    )
    day_id = json_body(generated)["program"]["days"][0]["id"]
    day_detail = await client.get(
        f"/api/v1/program/days/{day_id}", headers=_auth_headers(registered["access_token"])
    )
    planned_ids = {e["exercise"]["id"] for e in json_body(day_detail)["day"]["exercises"]}
    first_planned = json_body(day_detail)["day"]["exercises"][0]["exercise"]["id"]

    result = await db_session.execute(select(Exercise.id).order_by(Exercise.slug))
    unplanned = next(str(i) for i in result.scalars().all() if str(i) not in planned_ids)

    session_id = await _seed_session(
        db_session,
        user_id=user_id,
        local_date=date(2026, 8, 10),
        program_day_id=uuid.UUID(day_id),
    )
    # The unplanned exercise is logged FIRST, so only the position rule puts it last.
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=uuid.UUID(unplanned),
        set_index=1,
        reps=10,
        weight_kg="20",
        logged_at=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
    )
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=uuid.UUID(first_planned),
        set_index=1,
        reps=8,
        weight_kg="60",
        logged_at=datetime(2026, 8, 10, 18, 30, tzinfo=UTC),
    )

    response = await _detail(client, registered["access_token"], str(session_id))
    groups = [group["exercise"]["id"] for group in json_body(response)["session"]["exercises"]]
    assert groups == [first_planned, unplanned]


async def test_detail_of_a_session_with_no_sets_is_a_well_formed_empty_shape(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    session_id = await _seed_session(
        db_session, user_id=user_id, local_date=date(2026, 8, 10), status="abandoned"
    )

    response = await _detail(client, registered["access_token"], str(session_id))
    assert response.status_code == 200
    session = json_body(response)["session"]
    assert session["exercises"] == []
    assert session["set_count"] == 0
    assert session["exercise_count"] == 0
    assert session["status"] == "abandoned"


async def test_detail_shows_warmup_sets_flagged_rather_than_hidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # P2-ADR-04 excludes warm-ups from records and volume; T-27 renders them
    # "visually distinguished", which it can only do if they arrive flagged.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    session_id = await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, 10))
    exercise_id = await _first_exercise_id(db_session)
    for index, is_warmup in ((1, True), (2, False)):
        await _seed_set(
            db_session,
            user_id=user_id,
            session_id=session_id,
            exercise_id=exercise_id,
            set_index=index,
            reps=8,
            weight_kg="60",
            is_warmup=is_warmup,
            logged_at=datetime(2026, 8, 10, 18, index, tzinfo=UTC),
        )

    response = await _detail(client, registered["access_token"], str(session_id))
    sets = json_body(response)["session"]["exercises"][0]["sets"]
    assert [one_set["is_warmup"] for one_set in sets] == [True, False]


async def test_detail_resolves_the_exercise_name_in_the_callers_language(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client, language="en")
    user_id = uuid.UUID(registered["user"]["id"])
    session_id = await _seed_session(db_session, user_id=user_id, local_date=date(2026, 8, 10))
    exercise_id = await _first_exercise_id(db_session)
    await _seed_set(
        db_session,
        user_id=user_id,
        session_id=session_id,
        exercise_id=exercise_id,
        set_index=1,
        reps=8,
        weight_kg="60",
        logged_at=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
    )

    await set_rls_user(db_session, str(user_id))
    exercise = (
        await db_session.execute(select(Exercise).where(Exercise.id == exercise_id))
    ).scalar_one()

    response = await _detail(client, registered["access_token"], str(session_id))
    assert json_body(response)["session"]["exercises"][0]["exercise"]["name"] == exercise.name_en


async def test_a_finished_session_reads_back_through_history_and_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # End to end through the real endpoints only: start -> log -> finish -> read the
    # history row and the detail, with no seeded row anywhere in the path.
    registered = await _register_and_onboard(client)
    token = registered["access_token"]
    started = await client.post(_WORKOUTS, json={}, headers=_auth_headers(token))
    assert started.status_code == 201
    session_id = json_body(started)["session"]["id"]

    exercise_id = await _first_exercise_id(db_session)
    logged = await client.post(
        f"{_WORKOUTS}/{session_id}/sets",
        json={"exercise_id": str(exercise_id), "reps": 8, "weight_kg": 60},
        headers=_auth_headers(token),
    )
    assert logged.status_code == 201

    finished = await client.post(
        f"{_WORKOUTS}/{session_id}/finish",
        json={"notes": "felt strong"},
        headers=_auth_headers(token),
    )
    assert finished.status_code == 200

    history = await _history(client, token)
    assert history.status_code == 200
    item = json_body(history)["items"][0]
    assert item["id"] == session_id
    assert item["status"] == "completed"
    assert item["set_count"] == 1
    assert item["total_volume_kg"] == 480

    detail = await _detail(client, token, session_id)
    assert detail.status_code == 200
    session = json_body(detail)["session"]
    assert session["notes"] == "felt strong"
    assert session["total_volume_kg"] == 480
    assert session["exercises"][0]["sets"][0]["derived"] == {"volume_kg": 480, "e1rm_kg": 76}


async def test_history_respects_the_local_date_of_a_users_own_timezone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # `local_date` is resolved at write time through §4.2's timezone and stored, so the
    # history filter operates on the user's own calendar, not the server's.
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    yesterday = date(2026, 8, 9)
    await _seed_session(
        db_session,
        user_id=user_id,
        local_date=yesterday,
        # 23:00 UTC on the 9th is already the 10th in Cairo -- the stored local_date is
        # what the filter must honour, never a re-derivation from started_at.
        started_at=datetime(2026, 8, 9, 23, 0, tzinfo=UTC),
    )

    response = await _history(
        client, registered["access_token"], **{"from": "2026-08-09", "to": "2026-08-09"}
    )
    assert len(json_body(response)["items"]) == 1
    assert json_body(response)["items"][0]["local_date"] == "2026-08-09"


async def test_history_limit_bounds_are_enforced(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    assert (await _history(client, registered["access_token"], limit=0)).status_code == 422
    assert (await _history(client, registered["access_token"], limit=101)).status_code == 422


async def test_history_default_page_size_is_twenty(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    base = date(2026, 6, 1)
    for offset in range(25):
        await _seed_session(db_session, user_id=user_id, local_date=base + timedelta(days=offset))

    response = await _history(client, registered["access_token"])
    body = json_body(response)
    assert len(body["items"]) == 20
    assert body["next_cursor"] is not None
