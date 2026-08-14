"""§5.7 (POST/PATCH/DELETE /workouts/{id}/sets[/{set_id}]), P2-FR-006. Also covers
this task's own "done when": two concurrent POSTs for the same exercise produce
set_index 1 and 2 with no duplicate, and `is_record` fires once for a new best
rather than on every heavier set that follows it in the same session.

Every test drives set creation through the real POST endpoint now that it exists
(unlike test_workout_sessions.py, which had to seed workout_sets directly -- T-18's
own note that T-19 would be the first consumer of a real set-logging endpoint).
`db_session` is used only for the one place this task's requirements name explicitly:
proving the P2-ADR-09 parent RLS policy hides another user's set even by its own id,
not merely that the API's own ownership check does.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.database import set_rls_user
from app.models.workout import WorkoutSet
from tests.support import JSONDict, json_body

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_PROFILE = "/api/v1/profile"
_WORKOUTS = "/api/v1/workouts"
_EXERCISES = "/api/v1/exercises"
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
        _PROFILE, json=_profile_body(**overrides), headers=_auth_headers(registered["access_token"])
    )
    assert response.status_code == 201
    return registered


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


async def _finish(client: AsyncClient, access_token: str, session_id: str) -> Response:
    return await client.post(
        f"{_WORKOUTS}/{session_id}/finish", json={}, headers=_auth_headers(access_token)
    )


async def _abandon(client: AsyncClient, access_token: str, session_id: str) -> Response:
    return await client.post(
        f"{_WORKOUTS}/{session_id}/abandon", headers=_auth_headers(access_token)
    )


async def _create_set(
    client: AsyncClient, access_token: str, session_id: str, **body: object
) -> Response:
    return await client.post(
        f"{_WORKOUTS}/{session_id}/sets", json=body, headers=_auth_headers(access_token)
    )


async def _update_set(
    client: AsyncClient, access_token: str, session_id: str, set_id: str, **body: object
) -> Response:
    return await client.patch(
        f"{_WORKOUTS}/{session_id}/sets/{set_id}", json=body, headers=_auth_headers(access_token)
    )


async def _delete_set(
    client: AsyncClient, access_token: str, session_id: str, set_id: str
) -> Response:
    return await client.delete(
        f"{_WORKOUTS}/{session_id}/sets/{set_id}", headers=_auth_headers(access_token)
    )


async def _started_session_with_exercises(
    client: AsyncClient, access_token: str, count: int = 2
) -> tuple[str, list[str]]:
    exercise_ids = await _exercise_ids(client, access_token, count=count)
    started = await _start(client, access_token)
    assert started.status_code == 201
    session_id = json_body(started)["session"]["id"]
    return session_id, exercise_ids


# --- 409 PROFILE_REQUIRED (spec §5.1) ----------------------------------------------------


async def test_create_set_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _create_set(
        client,
        registered["access_token"],
        str(uuid.uuid4()),
        exercise_id=str(uuid.uuid4()),
        reps=5,
        weight_kg=40,
    )
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


# --- POST: happy path, set_index, derived, session_totals --------------------------------


async def test_create_set_assigns_set_index_one_and_returns_derived_and_totals(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=8,
        weight_kg=60,
        rpe=8,
        is_warmup=False,
    )
    assert response.status_code == 201
    body = json_body(response)
    created = body["set"]
    assert created["set_index"] == 1
    assert created["exercise_id"] == exercise_id
    assert created["reps"] == 8
    assert created["weight_kg"] == 60
    assert created["rpe"] == 8
    assert created["is_warmup"] is False
    # spec §5.7's own worked example: weight_kg=60, reps=8 -> volume_kg=480, e1rm_kg=76.
    assert created["derived"] == {"volume_kg": 480, "e1rm_kg": 76}
    assert body["session_totals"] == {"sets": 1, "volume_kg": 480}
    # No prior history at all for this exercise -- nothing to have beaten.
    assert body["is_record"] is None


async def test_set_index_increments_per_exercise_within_a_session(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_a, exercise_b] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    first = await _create_set(
        client, registered["access_token"], session_id, exercise_id=exercise_a, reps=5, weight_kg=40
    )
    second = await _create_set(
        client, registered["access_token"], session_id, exercise_id=exercise_a, reps=5, weight_kg=40
    )
    assert json_body(first)["set"]["set_index"] == 1
    assert json_body(second)["set"]["set_index"] == 2

    # A different exercise in the same session starts its own counter at 1.
    other = await _create_set(
        client, registered["access_token"], session_id, exercise_id=exercise_b, reps=5, weight_kg=40
    )
    assert json_body(other)["set"]["set_index"] == 1


async def test_set_index_is_never_accepted_from_the_client(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    # set_index has no field in WorkoutSetCreateRequest at all; extra="forbid" rejects
    # it with FastAPI's own body-parsing error, not the app's envelope.
    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
        set_index=99,
    )
    assert response.status_code == 422


async def test_deleting_a_set_leaves_a_gap_the_next_index_skips_over(client: AsyncClient) -> None:
    """§5.7 DELETE: "Remaining sets are not re-indexed" -- combined with `next_set_index`
    using MAX(set_index), not COUNT(*): after 1, 2, 3 exist and 2 is deleted, the next
    set for the same exercise must be 4, not 2 (which would collide) or 3."""
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    ids = []
    for _ in range(3):
        created = await _create_set(
            client,
            registered["access_token"],
            session_id,
            exercise_id=exercise_id,
            reps=5,
            weight_kg=40,
        )
        ids.append(json_body(created)["set"]["id"])

    deleted = await _delete_set(client, registered["access_token"], session_id, ids[1])
    assert deleted.status_code == 204
    assert deleted.content == b""

    fourth = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
    )
    assert json_body(fourth)["set"]["set_index"] == 4


async def test_two_concurrent_posts_for_the_same_exercise_produce_indices_one_and_two(
    client: AsyncClient,
) -> None:
    """This task's own "done when": no duplicate set_index under a real race."""
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    first, second = await asyncio.gather(
        _create_set(
            client,
            registered["access_token"],
            session_id,
            exercise_id=exercise_id,
            reps=5,
            weight_kg=40,
        ),
        _create_set(
            client,
            registered["access_token"],
            session_id,
            exercise_id=exercise_id,
            reps=5,
            weight_kg=40,
        ),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    indices = sorted([json_body(first)["set"]["set_index"], json_body(second)["set"]["set_index"]])
    assert indices == [1, 2]


# --- POST: 404 EXERCISE_NOT_FOUND, 404 SESSION_NOT_FOUND ----------------------------------


async def test_create_set_with_unknown_exercise_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, _ = await _started_session_with_exercises(
        client, registered["access_token"], count=1
    )

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=str(uuid.uuid4()),
        reps=5,
        weight_kg=40,
    )
    assert response.status_code == 404
    assert json_body(response)["code"] == "EXERCISE_NOT_FOUND"


async def test_create_set_with_malformed_exercise_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, _ = await _started_session_with_exercises(
        client, registered["access_token"], count=1
    )

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id="not-a-uuid",
        reps=5,
        weight_kg=40,
    )
    assert response.status_code == 404
    assert json_body(response)["code"] == "EXERCISE_NOT_FOUND"


async def test_create_set_on_unknown_session_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    [exercise_id] = await _exercise_ids(client, registered["access_token"], count=1)

    response = await _create_set(
        client,
        registered["access_token"],
        str(uuid.uuid4()),
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
    )
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


async def test_create_set_on_another_users_session_returns_404(client: AsyncClient) -> None:
    owner = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, owner["access_token"]
    )

    intruder = await _register_and_onboard(client)
    response = await _create_set(
        client, intruder["access_token"], session_id, exercise_id=exercise_id, reps=5, weight_kg=40
    )
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


# --- 409 SESSION_NOT_ACTIVE on POST/PATCH/DELETE ------------------------------------------


async def test_create_set_on_a_closed_session_returns_409(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    assert (await _abandon(client, registered["access_token"], session_id)).status_code == 200

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
    )
    assert response.status_code == 409
    assert json_body(response)["code"] == "SESSION_NOT_ACTIVE"


async def test_update_set_on_a_closed_session_returns_409(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
    )
    set_id = json_body(created)["set"]["id"]
    assert (await _abandon(client, registered["access_token"], session_id)).status_code == 200

    response = await _update_set(client, registered["access_token"], session_id, set_id, reps=6)
    assert response.status_code == 409
    assert json_body(response)["code"] == "SESSION_NOT_ACTIVE"


async def test_delete_set_on_a_closed_session_returns_409(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
    )
    set_id = json_body(created)["set"]["id"]
    assert (await _abandon(client, registered["access_token"], session_id)).status_code == 200

    response = await _delete_set(client, registered["access_token"], session_id, set_id)
    assert response.status_code == 409
    assert json_body(response)["code"] == "SESSION_NOT_ACTIVE"


# --- 404 SET_NOT_FOUND ----------------------------------------------------------------------


async def test_update_unknown_set_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, _ = await _started_session_with_exercises(
        client, registered["access_token"], count=1
    )

    response = await _update_set(
        client, registered["access_token"], session_id, str(uuid.uuid4()), reps=6
    )
    assert response.status_code == 404
    assert json_body(response)["code"] == "SET_NOT_FOUND"


async def test_update_malformed_set_id_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, _ = await _started_session_with_exercises(
        client, registered["access_token"], count=1
    )

    response = await _update_set(
        client, registered["access_token"], session_id, "not-a-uuid", reps=6
    )
    assert response.status_code == 404
    assert json_body(response)["code"] == "SET_NOT_FOUND"


async def test_delete_unknown_set_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, _ = await _started_session_with_exercises(
        client, registered["access_token"], count=1
    )

    response = await _delete_set(client, registered["access_token"], session_id, str(uuid.uuid4()))
    assert response.status_code == 404
    assert json_body(response)["code"] == "SET_NOT_FOUND"


async def test_a_set_belonging_to_another_session_is_404_not_found_in_this_one(
    client: AsyncClient,
) -> None:
    """§7.2: "Unknown set, or not in this session" -- same code either way. A set that
    genuinely exists, but under a *different* session of the *same* user, must still
    404 when addressed through the wrong session's URL."""
    registered = await _register_and_onboard(client)
    first_session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        first_session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
    )
    set_id = json_body(created)["set"]["id"]
    assert (await _abandon(client, registered["access_token"], first_session_id)).status_code == 200

    second = await _start(client, registered["access_token"])
    assert second.status_code == 201
    second_session_id = json_body(second)["session"]["id"]

    response = await _update_set(
        client, registered["access_token"], second_session_id, set_id, reps=6
    )
    assert response.status_code == 404
    assert json_body(response)["code"] == "SET_NOT_FOUND"


async def test_update_on_another_users_session_returns_404(client: AsyncClient) -> None:
    owner = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, owner["access_token"]
    )
    created = await _create_set(
        client, owner["access_token"], session_id, exercise_id=exercise_id, reps=5, weight_kg=40
    )
    set_id = json_body(created)["set"]["id"]

    intruder = await _register_and_onboard(client)
    response = await _update_set(client, intruder["access_token"], session_id, set_id, reps=6)
    assert response.status_code == 404
    assert json_body(response)["code"] == "SESSION_NOT_FOUND"


# --- PATCH: field acceptance, partial update, derived recomputed --------------------------


async def test_patch_updates_reps_and_recomputes_derived_and_totals(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=8,
        weight_kg=60,
    )
    set_id = json_body(created)["set"]["id"]

    response = await _update_set(client, registered["access_token"], session_id, set_id, reps=10)
    assert response.status_code == 200
    body = json_body(response)
    assert body["set"]["reps"] == 10
    assert body["set"]["weight_kg"] == 60
    # 60 * 10 = 600, e1rm = 60 * (1 + 10/30) = 80.
    assert body["set"]["derived"] == {"volume_kg": 600, "e1rm_kg": 80}
    assert body["session_totals"] == {"sets": 1, "volume_kg": 600}


async def test_patch_clears_rpe_when_sent_explicitly_null(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=8,
        weight_kg=60,
        rpe=8,
    )
    set_id = json_body(created)["set"]["id"]
    assert json_body(created)["set"]["rpe"] == 8

    response = await _update_set(client, registered["access_token"], session_id, set_id, rpe=None)
    assert response.status_code == 200
    assert json_body(response)["set"]["rpe"] is None


async def test_patch_rejects_exercise_id(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, other_exercise_id] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=8,
        weight_kg=60,
    )
    set_id = json_body(created)["set"]["id"]

    # exercise_id has no field in WorkoutSetPatchRequest at all; extra="forbid"
    # rejects it with FastAPI's own body-parsing error, not the app's envelope.
    response = await _update_set(
        client, registered["access_token"], session_id, set_id, exercise_id=other_exercise_id
    )
    assert response.status_code == 422


async def test_patch_with_an_empty_body_returns_422_validation_error(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=8,
        weight_kg=60,
    )
    set_id = json_body(created)["set"]["id"]

    response = await _update_set(client, registered["access_token"], session_id, set_id)
    assert response.status_code == 422
    assert json_body(response)["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "field,code",
    [("reps", "OUT_OF_RANGE"), ("weight_kg", "OUT_OF_RANGE"), ("is_warmup", "INVALID")],
)
async def test_patch_rejects_an_explicit_null_on_a_non_nullable_field(
    client: AsyncClient, field: str, code: str
) -> None:
    """Only `rpe` is nullable on the row (§4.7), so only `rpe: null` means "clear it"
    (covered above). `reps`/`weight_kg`/`is_warmup` are NOT NULL columns: sending an
    explicit null for one is a client bug, and `exclude_unset=True` cannot tell it
    from a real value on its own -- it only distinguishes sent from unsent -- so the
    service rejects it with the field's own §7.1 code rather than letting a NOT NULL
    violation surface as a 500.
    """
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=8,
        weight_kg=60,
    )
    set_id = json_body(created)["set"]["id"]

    response = await _update_set(
        client, registered["access_token"], session_id, set_id, **{field: None}
    )
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": field, "code": code}]


# --- §7.1 field validation -----------------------------------------------------------------


async def test_create_set_rejects_reps_out_of_range(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=0,
        weight_kg=40,
    )
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": "reps", "code": "OUT_OF_RANGE"}]


async def test_create_set_rejects_weight_kg_out_of_range(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=501,
    )
    assert response.status_code == 422
    assert json_body(response)["errors"] == [{"field": "weight_kg", "code": "OUT_OF_RANGE"}]


async def test_create_set_rejects_rpe_off_the_half_step(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
        rpe=7.3,
    )
    assert response.status_code == 422
    assert json_body(response)["errors"] == [{"field": "rpe", "code": "OUT_OF_RANGE"}]


async def test_create_set_accepts_a_bodyweight_zero_weight(client: AsyncClient) -> None:
    # §4.7's own note: "Zero is legitimate -- a bodyweight movement."
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=12,
        weight_kg=0,
    )
    assert response.status_code == 201
    assert json_body(response)["set"]["weight_kg"] == 0


# --- DELETE: happy path --------------------------------------------------------------------


async def test_delete_set_returns_204_and_the_set_is_gone(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )
    created = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
    )
    set_id = json_body(created)["set"]["id"]

    response = await _delete_set(client, registered["access_token"], session_id, set_id)
    assert response.status_code == 204
    assert response.content == b""

    # Deleted -- PATCHing it now 404s.
    follow_up = await _update_set(client, registered["access_token"], session_id, set_id, reps=6)
    assert follow_up.status_code == 404
    assert json_body(follow_up)["code"] == "SET_NOT_FOUND"


# --- Rate limit: 300 / hour per user (§7.3) -------------------------------------------------


async def test_sets_rate_limit_applies_across_post_patch_and_delete(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    for _ in range(300):
        response = await _create_set(
            client,
            registered["access_token"],
            session_id,
            exercise_id=exercise_id,
            reps=5,
            weight_kg=40,
        )
        assert response.status_code == 201

    refused = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=40,
    )
    assert refused.status_code == 429
    assert json_body(refused)["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers


# --- is_record: fires once, excludes warm-ups and abandoned sessions ----------------------


async def test_is_record_is_null_with_no_prior_history(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, registered["access_token"]
    )

    response = await _create_set(
        client,
        registered["access_token"],
        session_id,
        exercise_id=exercise_id,
        reps=8,
        weight_kg=60,
    )
    assert json_body(response)["is_record"] is None


async def test_is_record_is_null_for_a_set_that_does_not_beat_the_baseline(
    client: AsyncClient,
) -> None:
    """The other half of the record check: history exists, and this set simply is not
    better than it. `previous` is never reported for a set that did not win."""
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    [exercise_id] = await _exercise_ids(client, access_token, count=1)

    # Baseline: 80kg x 5 -> e1rm 93.33.
    baseline_started = await _start(client, access_token)
    baseline_session_id = json_body(baseline_started)["session"]["id"]
    await _create_set(
        client, access_token, baseline_session_id, exercise_id=exercise_id, reps=5, weight_kg=80
    )
    assert (await _finish(client, access_token, baseline_session_id)).status_code == 200

    # 60kg x 5 -> e1rm 70.0, comfortably short of 93.33.
    started = await _start(client, access_token)
    session_id = json_body(started)["session"]["id"]
    response = await _create_set(
        client, access_token, session_id, exercise_id=exercise_id, reps=5, weight_kg=60
    )
    assert json_body(response)["set"]["derived"]["e1rm_kg"] == 70.0
    assert json_body(response)["is_record"] is None


async def test_is_record_fires_once_not_on_every_heavier_set_in_the_same_session(
    client: AsyncClient,
) -> None:
    """This task's own "done when", verbatim."""
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    [exercise_id] = await _exercise_ids(client, access_token, count=1)

    # A completed session establishes a real baseline: 50kg x 5 -> e1rm 58.33.
    baseline_started = await _start(client, access_token)
    baseline_session_id = json_body(baseline_started)["session"]["id"]
    await _create_set(
        client, access_token, baseline_session_id, exercise_id=exercise_id, reps=5, weight_kg=50
    )
    finished = await _finish(client, access_token, baseline_session_id)
    assert finished.status_code == 200

    # A fresh session ramps up three sets, each heavier than the last.
    started = await _start(client, access_token)
    session_id = json_body(started)["session"]["id"]

    first = await _create_set(
        client, access_token, session_id, exercise_id=exercise_id, reps=5, weight_kg=60
    )
    first_body = json_body(first)
    assert first_body["set"]["derived"]["e1rm_kg"] == 70.0
    assert first_body["is_record"] == {"kind": "e1rm", "previous": 58.33}

    second = await _create_set(
        client, access_token, session_id, exercise_id=exercise_id, reps=5, weight_kg=70
    )
    assert json_body(second)["set"]["derived"]["e1rm_kg"] == 81.67
    assert json_body(second)["is_record"] is None, "already claimed by the first set this session"

    third = await _create_set(
        client, access_token, session_id, exercise_id=exercise_id, reps=5, weight_kg=80
    )
    assert json_body(third)["set"]["derived"]["e1rm_kg"] == 93.33
    assert json_body(third)["is_record"] is None, "still already claimed this session"


async def test_is_record_ignores_warmup_sets_both_as_target_and_as_history(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    [exercise_id] = await _exercise_ids(client, access_token, count=1)

    baseline_started = await _start(client, access_token)
    baseline_session_id = json_body(baseline_started)["session"]["id"]
    await _create_set(
        client, access_token, baseline_session_id, exercise_id=exercise_id, reps=5, weight_kg=50
    )
    assert (await _finish(client, access_token, baseline_session_id)).status_code == 200

    started = await _start(client, access_token)
    session_id = json_body(started)["session"]["id"]

    # A heavier warm-up set must never be flagged as a record.
    warmup = await _create_set(
        client,
        access_token,
        session_id,
        exercise_id=exercise_id,
        reps=5,
        weight_kg=90,
        is_warmup=True,
    )
    assert json_body(warmup)["is_record"] is None

    # A genuine work set that beats the real baseline still fires -- the warm-up
    # above did not silently raise the bar it is compared against.
    work_set = await _create_set(
        client, access_token, session_id, exercise_id=exercise_id, reps=5, weight_kg=60
    )
    assert json_body(work_set)["is_record"] == {"kind": "e1rm", "previous": 58.33}


async def test_is_record_excludes_an_abandoned_sessions_sets_from_the_baseline(
    client: AsyncClient,
) -> None:
    """§5.8/P2-ADR-04: an abandoned session's sets are excluded from records. A heavy
    set logged and then abandoned must not count as the baseline a later, lighter
    (but still genuinely record-breaking) set is compared against."""
    registered = await _register_and_onboard(client)
    access_token = registered["access_token"]
    [exercise_id] = await _exercise_ids(client, access_token, count=1)

    # Abandoned: 100kg x 1 -> e1rm 103.33. Must never become anyone's baseline.
    abandoned_started = await _start(client, access_token)
    abandoned_session_id = json_body(abandoned_started)["session"]["id"]
    await _create_set(
        client, access_token, abandoned_session_id, exercise_id=exercise_id, reps=1, weight_kg=100
    )
    assert (await _abandon(client, access_token, abandoned_session_id)).status_code == 200

    # Completed: 60kg x 8 -> e1rm 76.0. This is the real baseline.
    completed_started = await _start(client, access_token)
    completed_session_id = json_body(completed_started)["session"]["id"]
    await _create_set(
        client, access_token, completed_session_id, exercise_id=exercise_id, reps=8, weight_kg=60
    )
    assert (await _finish(client, access_token, completed_session_id)).status_code == 200

    # 70kg x 8 -> e1rm 88.67: beats the real (completed) baseline of 76, but would
    # NOT beat the abandoned session's 103.33 had it wrongly counted.
    started = await _start(client, access_token)
    session_id = json_body(started)["session"]["id"]
    response = await _create_set(
        client, access_token, session_id, exercise_id=exercise_id, reps=8, weight_kg=70
    )
    assert json_body(response)["is_record"] == {"kind": "e1rm", "previous": 76.0}


# --- P2-ADR-09: a set in another user's session is invisible even with its id -------------


async def test_a_set_in_another_users_session_is_invisible_via_rls_directly(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """workout_sets has no user_id of its own (P2-ADR-09); ownership reads through the
    parent workout_sessions row. This proves the RLS policy itself hides the row when
    queried directly as another user by its exact id -- not merely that the API's own
    session_id-scoped ownership check (`get_set`) does, which is a different,
    redundant layer above the database's own guarantee.
    """
    owner = await _register_and_onboard(client)
    owner_id = uuid.UUID(owner["user"]["id"])
    session_id, [exercise_id, _] = await _started_session_with_exercises(
        client, owner["access_token"]
    )
    created = await _create_set(
        client, owner["access_token"], session_id, exercise_id=exercise_id, reps=5, weight_kg=40
    )
    set_id = uuid.UUID(json_body(created)["set"]["id"])

    intruder = await _register_and_onboard(client)
    intruder_id = uuid.UUID(intruder["user"]["id"])
    assert intruder_id != owner_id

    await set_rls_user(db_session, str(intruder_id))
    result = await db_session.execute(select(WorkoutSet).where(WorkoutSet.id == set_id))
    assert result.scalar_one_or_none() is None, (
        "a set belonging to another user's session must be invisible to RLS even by its own id"
    )
