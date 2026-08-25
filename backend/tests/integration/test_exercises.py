"""§5.2 (GET /exercises, GET /exercises/{id}), P2-FR-001, P2-ADR-02.

Per this task's own "done when": the seed runs twice with no duplicates (proven by
every other test here even being able to run at all -- the full suite's migration
run, exercised once per session by conftest.py, already runs `alembic upgrade head`
against a fresh database; idempotency itself is proven at the migration level, not
re-proven per HTTP test), filters combine with AND, an Arabic-language profile
receives Arabic names (also covered from the cross-tenant angle in
tests/security/test_cross_tenant.py), and the cross-tenant matrix has no new findings
(same file).

T-16b (spec §5.2's note, added after T-16 shipped): three tests below --
`test_q_filter_matches_arabic_substring_within_definite_article`,
`test_q_filter_matches_arabic_bench_press_entries` and
`test_q_filter_folds_arabic_alef_variants` -- are the note's own three named proof
queries (`صدر`, `بنش`, `اسكوات`). Only the third actually failed against T-16's
`unaccent`-based implementation; the first two already passed, since plain substring
matching handles them without any folding. `test_q_filter_is_diacritic_insensitive`
(the `unaccent`-driven "Café" case) is gone: `unaccent` itself is gone, dropped as a
dependency that was not earning its place for a seed library with no accented Latin
names (§11 item 9).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.ids import new_id
from app.core.rate_limit import limiter
from tests.support import JSONDict, json_body

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_PROFILE = "/api/v1/profile"
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


async def _onboard(client: AsyncClient, access_token: str, **overrides: object) -> Response:
    return await client.post(
        _PROFILE, json=_profile_body(**overrides), headers=_auth_headers(access_token)
    )


async def _list_exercises(client: AsyncClient, access_token: str, **params: str | int) -> Response:
    return await client.get(_EXERCISES, params=params, headers=_auth_headers(access_token))


async def _get_exercise(client: AsyncClient, access_token: str, exercise_id: str) -> Response:
    return await client.get(f"{_EXERCISES}/{exercise_id}", headers=_auth_headers(access_token))


_INSERT_SQL = text(
    "INSERT INTO exercises (id, slug, name_en, name_ar, primary_muscle, equipment, "
    "movement_pattern, is_compound, difficulty, instructions_en, instructions_ar, "
    "is_active) VALUES (:id, :slug, :name_en, :name_ar, :primary_muscle, :equipment, "
    ":movement_pattern, :is_compound, :difficulty, :instructions_en, :instructions_ar, "
    ":is_active)"
)


async def _insert_synthetic_exercise(migrator_database_url: str, **overrides: object) -> uuid.UUID:
    """exercises is granted SELECT only to gymak_app (§4.10) -- no repository or test
    using the app-role `client`/`db_session` can ever INSERT here, matching
    production, where only T-16's own data migration (running as gymak_migrator)
    populates this table. Seeded over a dedicated migrator connection for the same
    reason tests/unit/test_models.py's identical helper is.
    """
    params: dict[str, object] = {
        "id": new_id(),
        "slug": f"test-{uuid.uuid4()}",
        "name_en": "Café Curl",
        "name_ar": "تجعيد تجريبي",
        "primary_muscle": "biceps",
        "equipment": "dumbbell",
        "movement_pattern": "isolation",
        "is_compound": False,
        "difficulty": "beginner",
        "instructions_en": "Test instructions.",
        "instructions_ar": "تعليمات تجريبية.",
        "is_active": True,
    }
    params.update(overrides)
    engine = create_async_engine(migrator_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(_INSERT_SQL, params)
    finally:
        await engine.dispose()
    exercise_id = params["id"]
    assert isinstance(exercise_id, uuid.UUID)
    return exercise_id


# --- 409 PROFILE_REQUIRED (spec §5.1) ------------------------------------------------------


async def test_list_exercises_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _list_exercises(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


async def test_get_exercise_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _get_exercise(client, registered["access_token"], str(new_id()))
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


# --- GET /exercises: filters, language resolution, pagination -----------------------------


async def test_list_exercises_happy_path_shape(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _list_exercises(client, registered["access_token"], limit=5)
    assert response.status_code == 200
    body = json_body(response)
    assert len(body["items"]) == 5
    item = body["items"][0]
    assert set(item) == {
        "id",
        "slug",
        "name",
        "primary_muscle",
        "secondary_muscles",
        "equipment",
        "movement_pattern",
        "is_compound",
        "difficulty",
        # Custom-exercise support: the client badges its own rows and shows edit/delete
        # only for them, so every list item says which kind it is. Seeded rows are false.
        "is_custom",
    }
    assert "instructions" not in item, "the list view must not carry instructions (§5.2)"
    assert item["is_custom"] is False, "a seeded row is not anyone's custom exercise"


async def test_muscle_filter_returns_only_that_primary_muscle(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _list_exercises(client, registered["access_token"], muscle="calves", limit=50)
    assert response.status_code == 200
    items = json_body(response)["items"]
    assert items, "expected at least one seeded calves exercise"
    assert all(item["primary_muscle"] == "calves" for item in items)


async def test_equipment_filter_returns_only_that_equipment(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _list_exercises(
        client, registered["access_token"], equipment="kettlebell", limit=50
    )
    assert response.status_code == 200
    items = json_body(response)["items"]
    assert items, "expected at least one seeded kettlebell exercise"
    assert all(item["equipment"] == "kettlebell" for item in items)


async def test_filters_combine_with_and_not_or(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    both = await _list_exercises(
        client, registered["access_token"], muscle="chest", equipment="dumbbell", limit=50
    )
    assert both.status_code == 200
    both_items = json_body(both)["items"]
    assert both_items, "expected at least one chest + dumbbell exercise in the seed data"
    for item in both_items:
        assert item["primary_muscle"] == "chest"
        assert item["equipment"] == "dumbbell"

    # No seeded row is both a calves exercise and barbell-equipped. If the filters were
    # OR'd instead of AND'd, this would return every calves row plus every barbell row --
    # decisively non-empty. AND'd, it must be empty.
    neither = await _list_exercises(
        client, registered["access_token"], muscle="calves", equipment="barbell", limit=50
    )
    assert neither.status_code == 200
    assert json_body(neither)["items"] == []


async def test_q_filter_is_case_insensitive(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"], language="en")

    response = await _list_exercises(client, registered["access_token"], q="SQUAT")
    assert response.status_code == 200
    names = [item["name"] for item in json_body(response)["items"]]
    assert any("squat" in name.lower() for name in names)


async def test_q_filter_matches_arabic_name(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"], language="ar")

    # "سكوات" (squat) appears in several seeded Arabic names.
    response = await _list_exercises(client, registered["access_token"], q="سكوات")
    assert response.status_code == 200
    items = json_body(response)["items"]
    assert items
    assert all("سكوات" in item["name"] for item in items)


async def test_q_filter_matches_arabic_substring_within_definite_article(
    client: AsyncClient,
) -> None:
    """§5.2's note: "a query of صدر must match a name of الصدر (substring match handles
    this)" -- proof point 1 of 3."""
    registered = await _register(client)
    await _onboard(client, registered["access_token"], language="ar")

    response = await _list_exercises(client, registered["access_token"], q="صدر")
    assert response.status_code == 200
    names = [item["name"] for item in json_body(response)["items"]]
    assert names
    assert all("صدر" in name for name in names)


async def test_q_filter_matches_arabic_bench_press_entries(client: AsyncClient) -> None:
    """§5.2's note -- proof point 2 of 3: q=بنش finds the bench-press entries."""
    registered = await _register(client)
    await _onboard(client, registered["access_token"], language="ar")

    response = await _list_exercises(client, registered["access_token"], q="بنش")
    assert response.status_code == 200
    names = [item["name"] for item in json_body(response)["items"]]
    assert names
    assert all("بنش" in name for name in names)


async def test_q_filter_folds_arabic_alef_variants(
    client: AsyncClient, migrator_database_url: str
) -> None:
    """§5.2's note -- proof point 3 of 3: a query typed with a plain alef (ا, U+0627)
    must find a name written with an alef variant (إ, U+0625 here). `unaccent` cannot
    do this -- its default rules file is Latin/Greek/Cyrillic only -- which is the
    actual defect the note describes."""
    await _insert_synthetic_exercise(
        migrator_database_url,
        slug=f"test-alef-{uuid.uuid4()}",
        name_ar="إسكوات تجريبي",
    )
    registered = await _register(client)
    await _onboard(client, registered["access_token"], language="ar")

    response = await _list_exercises(client, registered["access_token"], q="اسكوات")
    assert response.status_code == 200
    names = [item["name"] for item in json_body(response)["items"]]
    assert "إسكوات تجريبي" in names


async def test_inactive_exercise_excluded_from_list_but_resolves_by_id(
    client: AsyncClient, migrator_database_url: str
) -> None:
    """P2-ADR-02: a deactivated exercise "must not vanish from a session logged three
    months ago" -- excluded from the list, but still resolvable by id."""
    exercise_id = await _insert_synthetic_exercise(
        migrator_database_url,
        slug=f"test-inactive-{uuid.uuid4()}",
        primary_muscle="obliques",
        equipment="band",
        is_active=False,
    )
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    listing = await _list_exercises(
        client, registered["access_token"], muscle="obliques", equipment="band"
    )
    assert listing.status_code == 200
    assert json_body(listing)["items"] == [], "an inactive row must never appear in the list"

    detail = await _get_exercise(client, registered["access_token"], str(exercise_id))
    assert detail.status_code == 200
    assert json_body(detail)["exercise"]["id"] == str(exercise_id)


async def test_malformed_cursor_returns_validation_error_not_a_crash(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _list_exercises(client, registered["access_token"], cursor="not-base64!!")
    assert response.status_code == 422
    assert json_body(response)["code"] == "VALIDATION_ERROR"


async def test_cursor_pagination_has_no_duplicates_and_terminates(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    seen_ids: list[str] = []
    cursor: str | None = None
    for _ in range(30):  # generously more than 57 seeded rows / 10 per page needs
        params: dict[str, str | int] = {"limit": 10}
        if cursor is not None:
            params["cursor"] = cursor
        response = await _list_exercises(client, registered["access_token"], **params)
        assert response.status_code == 200
        body = json_body(response)
        page_ids = [item["id"] for item in body["items"]]
        assert not (set(page_ids) & set(seen_ids)), "cursor pagination must not repeat a row"
        seen_ids.extend(page_ids)
        cursor = body["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("pagination did not terminate within 30 pages")

    # spec requirement: "at least 50 movements" -- a lower bound, tolerant of any
    # synthetic rows other tests in this session may have added.
    assert len(seen_ids) >= 50


async def test_exercises_is_rate_limited_at_120_per_hour_per_user(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    for _ in range(120):
        response = await _list_exercises(client, registered["access_token"], limit=1)
        assert response.status_code == 200

    refused = await _list_exercises(client, registered["access_token"], limit=1)
    assert refused.status_code == 429
    body = json_body(refused)
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers
    retry_after = int(refused.headers["Retry-After"])
    assert 1 <= retry_after <= 3600


# --- GET /exercises/{id} --------------------------------------------------------------------


async def test_get_exercise_by_id_includes_instructions(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"], language="en")

    listing = await _list_exercises(client, registered["access_token"], limit=1)
    exercise_id = json_body(listing)["items"][0]["id"]

    response = await _get_exercise(client, registered["access_token"], exercise_id)
    assert response.status_code == 200
    exercise = json_body(response)["exercise"]
    assert exercise["id"] == exercise_id
    assert isinstance(exercise["instructions"], str)
    assert len(exercise["instructions"]) > 0


async def test_get_exercise_unknown_id_returns_404(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _get_exercise(client, registered["access_token"], str(new_id()))
    assert response.status_code == 404
    assert json_body(response)["code"] == "EXERCISE_NOT_FOUND"


async def test_get_exercise_malformed_id_returns_404_not_a_validation_error(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _get_exercise(client, registered["access_token"], "not-a-uuid")
    assert response.status_code == 404
    assert json_body(response)["code"] == "EXERCISE_NOT_FOUND"


# --- Custom exercises (owner-authorised departure from §1.2) ------------------------------


def _custom_body(**overrides: object) -> JSONDict:
    body: dict[str, object] = {
        "name": "Landmine Press",
        "primary_muscle": "chest",
        "equipment": "barbell",
        "movement_pattern": "horizontal_push",
        "difficulty": "beginner",
    }
    body.update(overrides)
    return body


async def _create_custom(client: AsyncClient, access_token: str, **overrides: object) -> Response:
    return await client.post(
        _EXERCISES, json=_custom_body(**overrides), headers=_auth_headers(access_token)
    )


async def test_create_custom_exercise_happy_path(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _create_custom(client, registered["access_token"])
    assert response.status_code == 201, response.text
    exercise = json_body(response)["exercise"]
    assert exercise["name"] == "Landmine Press"
    assert exercise["is_custom"] is True
    assert exercise["primary_muscle"] == "chest"
    assert exercise["instructions"] == ""


async def test_custom_exercise_appears_in_the_owners_library(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])
    created = await _create_custom(client, registered["access_token"])
    exercise_id = json_body(created)["exercise"]["id"]

    listed = await _list_exercises(client, registered["access_token"], limit=100)
    assert listed.status_code == 200
    items = json_body(listed)["items"]
    match = [item for item in items if item["id"] == exercise_id]
    assert len(match) == 1, "the owner's own exercise belongs in their library listing"
    assert match[0]["is_custom"] is True
    assert any(item["is_custom"] is False for item in items), "seeded rows are still there too"


async def test_custom_exercise_is_found_by_the_q_filter(client: AsyncClient) -> None:
    """§5.2's filters apply to custom rows identically -- including the Arabic
    normalisation, since a custom row's name_ar is a real name like any other."""
    registered = await _register(client)
    await _onboard(client, registered["access_token"])
    await _create_custom(client, registered["access_token"], name="زحف الدب")

    found = await _list_exercises(client, registered["access_token"], q="زحف", limit=100)
    assert found.status_code == 200
    names = [item["name"] for item in json_body(found)["items"]]
    assert "زحف الدب" in names


async def test_one_typed_name_fills_both_languages(client: AsyncClient) -> None:
    """The decision recorded in `exercise_repo.create_custom`: a user types one name and
    it is written to both name columns. The point is what happens when the profile
    language changes -- §5.2 resolves the display name server-side, so a blank
    other-language column would render this row as an empty string. It must not.
    """
    registered = await _register(client)
    # _onboard defaults language to "ar"; the name below is typed in Arabic.
    await _onboard(client, registered["access_token"])
    created = await _create_custom(client, registered["access_token"], name="ضغط أرضي")
    exercise_id = json_body(created)["exercise"]["id"]

    switched = await client.patch(
        _PROFILE, json={"language": "en"}, headers=_auth_headers(registered["access_token"])
    )
    assert switched.status_code == 200

    fetched = await _get_exercise(client, registered["access_token"], exercise_id)
    assert fetched.status_code == 200
    name = json_body(fetched)["exercise"]["name"]
    assert name == "ضغط أرضي", "the typed name must survive a language switch"
    assert name != ""


async def test_two_exercises_with_the_same_name_both_succeed(client: AsyncClient) -> None:
    """The slug-collision decision: custom slugs are per-user prefixed AND carry the
    row's own id, so one user naming two exercises identically is not a failed INSERT.
    """
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    first = await _create_custom(client, registered["access_token"], name="Bench Press")
    second = await _create_custom(client, registered["access_token"], name="Bench Press")
    assert first.status_code == 201
    assert second.status_code == 201, second.text
    first_body = json_body(first)["exercise"]
    second_body = json_body(second)["exercise"]
    assert first_body["id"] != second_body["id"]
    assert first_body["slug"] != second_body["slug"]


async def test_two_users_may_invent_the_same_exercise_name(client: AsyncClient) -> None:
    user_a = await _register(client)
    await _onboard(client, user_a["access_token"])
    user_b = await _register(client)
    await _onboard(client, user_b["access_token"])

    first = await _create_custom(client, user_a["access_token"], name="Sled Push")
    second = await _create_custom(client, user_b["access_token"], name="Sled Push")
    assert first.status_code == 201
    assert second.status_code == 201, second.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("primary_muscle", "spleen"),
        ("equipment", "sledgehammer"),
        ("movement_pattern", "wiggle"),
        ("difficulty", "impossible"),
    ],
)
async def test_create_rejects_values_outside_the_closed_vocabularies(
    client: AsyncClient, field: str, value: str
) -> None:
    """Validated against the same tuples the CHECK constraints are built from, so a
    custom row can never carry a value the rest of the system cannot handle."""
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _create_custom(client, registered["access_token"], **{field: value})
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert any(error["field"] == field for error in body["errors"])


async def test_create_rejects_an_unknown_secondary_muscle(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])

    response = await _create_custom(
        client, registered["access_token"], secondary_muscles=["triceps", "gills"]
    )
    assert response.status_code == 422
    assert any(error["field"] == "secondary_muscles" for error in json_body(response)["errors"])


async def test_update_own_custom_exercise(client: AsyncClient) -> None:
    registered = await _register(client)
    await _onboard(client, registered["access_token"])
    created = await _create_custom(client, registered["access_token"])
    exercise_id = json_body(created)["exercise"]["id"]

    patched = await client.patch(
        f"{_EXERCISES}/{exercise_id}",
        json={"name": "Landmine Press (heavy)", "difficulty": "advanced"},
        headers=_auth_headers(registered["access_token"]),
    )
    assert patched.status_code == 200, patched.text
    exercise = json_body(patched)["exercise"]
    assert exercise["name"] == "Landmine Press (heavy)"
    assert exercise["difficulty"] == "advanced"
    # Untouched fields keep their values -- PATCH, not PUT.
    assert exercise["primary_muscle"] == "chest"


async def test_delete_is_a_soft_delete_that_still_resolves_by_id(client: AsyncClient) -> None:
    """P2-ADR-02's mechanism, reused: a retired custom exercise leaves the library but a
    session that logged it must still be able to name it."""
    registered = await _register(client)
    await _onboard(client, registered["access_token"])
    created = await _create_custom(client, registered["access_token"])
    exercise_id = json_body(created)["exercise"]["id"]

    deleted = await client.delete(
        f"{_EXERCISES}/{exercise_id}", headers=_auth_headers(registered["access_token"])
    )
    assert deleted.status_code == 200, deleted.text
    assert json_body(deleted)["is_active"] is False

    listed = await _list_exercises(client, registered["access_token"], limit=100)
    assert all(item["id"] != exercise_id for item in json_body(listed)["items"])

    resolved = await _get_exercise(client, registered["access_token"], exercise_id)
    assert resolved.status_code == 200, "a soft-deleted row must still resolve by id"


async def test_a_logged_custom_exercise_survives_its_own_soft_delete(client: AsyncClient) -> None:
    """The reason the delete is soft at all: workout_sets.exercise_id is ON DELETE
    RESTRICT, so a hard delete of a logged-against exercise is impossible. Retiring one
    must not break the session that used it."""
    registered = await _register(client)
    await _onboard(client, registered["access_token"])
    token = registered["access_token"]
    created = await _create_custom(client, token)
    exercise_id = json_body(created)["exercise"]["id"]

    started = await client.post("/api/v1/workouts", json={}, headers=_auth_headers(token))
    assert started.status_code == 201
    session_id = json_body(started)["session"]["id"]
    logged = await client.post(
        f"/api/v1/workouts/{session_id}/sets",
        json={"exercise_id": exercise_id, "reps": 8, "weight_kg": 40},
        headers=_auth_headers(token),
    )
    assert logged.status_code == 201, logged.text

    deleted = await client.delete(f"{_EXERCISES}/{exercise_id}", headers=_auth_headers(token))
    assert deleted.status_code == 200
    resolved = await _get_exercise(client, token, exercise_id)
    assert resolved.status_code == 200


async def test_create_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _create_custom(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"
