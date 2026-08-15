"""§5.10 (PUT/GET/DELETE /body-weight), P2-FR-009/010, P2-ADR-06.

This task's own "done when" drives the two heaviest sections below: the two-writer
coupling (PUT -> profiles.weight_kg, and PATCH /profile -> today's body-weight entry)
proven in both directions, and the future-date check proven to resolve through the
caller's own timezone rather than UTC.

No clock-mocking exists in this suite (see test_workout_sessions.py's own
`test_local_date_is_resolved_through_the_profile_timezone_not_utc`): every "today"
below is computed the same way the server computes it -- `datetime.now(UTC)` resolved
through the profile's own IANA zone at call time -- rather than assumed from the test
process's local clock, which need not agree with either UTC or Africa/Cairo.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.database import set_rls_user
from app.models.body_weight import BodyWeightEntry
from tests.support import JSONDict, json_body

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_PROFILE = "/api/v1/profile"
_BODY_WEIGHT = "/api/v1/body-weight"
_PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _isolated_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


def _today_cairo() -> date:
    """Africa/Cairo is every test user's timezone below unless a test explicitly
    PATCHes a different one -- profiles.timezone's own default (§4.2)."""
    return datetime.now(UTC).astimezone(ZoneInfo("Africa/Cairo")).date()


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


async def _put_weight(
    client: AsyncClient, access_token: str, *, measured_on: str, weight_kg: object, **rest: object
) -> Response:
    body: JSONDict = {"measured_on": measured_on, "weight_kg": weight_kg, **rest}
    return await client.put(_BODY_WEIGHT, json=body, headers=_auth_headers(access_token))


async def _get_weight(client: AsyncClient, access_token: str, **params: str) -> Response:
    return await client.get(_BODY_WEIGHT, params=params, headers=_auth_headers(access_token))


async def _delete_weight(client: AsyncClient, access_token: str, measured_on: str) -> Response:
    return await client.delete(f"{_BODY_WEIGHT}/{measured_on}", headers=_auth_headers(access_token))


async def _patch_profile(client: AsyncClient, access_token: str, body: JSONDict) -> Response:
    return await client.patch(_PROFILE, json=body, headers=_auth_headers(access_token))


async def _get_profile(client: AsyncClient, access_token: str) -> Response:
    return await client.get(_PROFILE, headers=_auth_headers(access_token))


async def _load_entry(
    db_session: AsyncSession, user_id: uuid.UUID, measured_on: date
) -> BodyWeightEntry | None:
    # body_weight_entries is FORCE-RLS; binding this user's own id before reading their
    # own row is exactly how the app itself would read it, not a bypass (see
    # app/database.py's set_rls_user docstring; test_cross_tenant.py's _load_profile
    # does the same for `profiles`).
    await set_rls_user(db_session, str(user_id))
    result = await db_session.execute(
        select(BodyWeightEntry).where(
            BodyWeightEntry.user_id == user_id, BodyWeightEntry.measured_on == measured_on
        )
    )
    return result.scalar_one_or_none()


# --- 409 PROFILE_REQUIRED (spec §5.1) ----------------------------------------------------


async def test_put_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _put_weight(
        client, registered["access_token"], measured_on=_today_cairo().isoformat(), weight_kg=75
    )
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


async def test_get_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _get_weight(client, registered["access_token"])
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


async def test_delete_requires_a_completed_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _delete_weight(client, registered["access_token"], _today_cairo().isoformat())
    assert response.status_code == 409
    assert json_body(response)["code"] == "PROFILE_REQUIRED"


# --- PUT: happy path, upsert-replaces-same-day --------------------------------------------


async def test_put_creates_an_entry_and_updates_profile_weight(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo().isoformat()

    response = await _put_weight(
        client, registered["access_token"], measured_on=today, weight_kg=73.4, note="after gym"
    )
    assert response.status_code == 200
    body = json_body(response)
    assert body["entry"]["measured_on"] == today
    assert body["entry"]["weight_kg"] == 73.4
    assert body["entry"]["note"] == "after gym"
    assert body["profile_weight_updated"] is True

    profile = await _get_profile(client, registered["access_token"])
    assert json_body(profile)["profile"]["weight_kg"] == 73.4


async def test_put_same_day_twice_replaces_not_duplicates(client: AsyncClient) -> None:
    """§10.2's own manual check, automated: "Log body weight for today, then again
    with a different number -> one entry, the second value.\""""
    registered = await _register_and_onboard(client)
    today = _today_cairo().isoformat()

    first = await _put_weight(client, registered["access_token"], measured_on=today, weight_kg=75)
    assert first.status_code == 200
    second = await _put_weight(client, registered["access_token"], measured_on=today, weight_kg=78)
    assert second.status_code == 200
    assert json_body(second)["entry"]["weight_kg"] == 78
    assert json_body(second)["profile_weight_updated"] is True

    listed = await _get_weight(client, registered["access_token"])
    entries = json_body(listed)["entries"]
    assert [e for e in entries if e["measured_on"] == today] == [
        {"measured_on": today, "weight_kg": 78}
    ]


async def test_put_an_older_date_does_not_update_profile_weight(client: AsyncClient) -> None:
    """P2-ADR-06: "updates profiles.weight_kg if -- and only if -- the entry is the
    newest one for that user." A backfilled older day must not roll the cached head
    backwards."""
    registered = await _register_and_onboard(client)
    today = _today_cairo()

    newest = await _put_weight(
        client, registered["access_token"], measured_on=today.isoformat(), weight_kg=75
    )
    assert json_body(newest)["profile_weight_updated"] is True

    backfilled = await _put_weight(
        client,
        registered["access_token"],
        measured_on=(today - timedelta(days=10)).isoformat(),
        weight_kg=90,
    )
    assert backfilled.status_code == 200
    assert json_body(backfilled)["profile_weight_updated"] is False

    profile = await _get_profile(client, registered["access_token"])
    assert json_body(profile)["profile"]["weight_kg"] == 75, (
        "a backfilled older entry must never roll profiles.weight_kg backwards"
    )


# --- PUT: §7.1 field validation -------------------------------------------------------------


@pytest.mark.parametrize("weight_kg", [29, 301])
async def test_put_rejects_weight_kg_out_of_range(client: AsyncClient, weight_kg: int) -> None:
    registered = await _register_and_onboard(client)
    response = await _put_weight(
        client,
        registered["access_token"],
        measured_on=_today_cairo().isoformat(),
        weight_kg=weight_kg,
    )
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": "weight_kg", "code": "OUT_OF_RANGE"}]


async def test_put_rejects_a_future_date(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    future = (_today_cairo() + timedelta(days=5)).isoformat()

    response = await _put_weight(
        client, registered["access_token"], measured_on=future, weight_kg=75
    )
    assert response.status_code == 422
    body = json_body(response)
    assert body["code"] == "VALIDATION_ERROR"
    assert body["errors"] == [{"field": "measured_on", "code": "IN_FUTURE"}]


async def test_put_rejects_a_date_before_2000(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _put_weight(
        client, registered["access_token"], measured_on="1999-12-31", weight_kg=75
    )
    assert response.status_code == 422
    assert json_body(response)["errors"] == [{"field": "measured_on", "code": "IN_FUTURE"}]


async def test_put_rejects_a_malformed_date(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _put_weight(
        client, registered["access_token"], measured_on="not-a-date", weight_kg=75
    )
    assert response.status_code == 422
    assert json_body(response)["errors"] == [{"field": "measured_on", "code": "IN_FUTURE"}]


async def test_put_accepts_today_exactly_the_boundary(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _put_weight(
        client, registered["access_token"], measured_on=_today_cairo().isoformat(), weight_kg=75
    )
    assert response.status_code == 200


async def test_put_rejects_a_note_over_200_characters(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _put_weight(
        client,
        registered["access_token"],
        measured_on=_today_cairo().isoformat(),
        weight_kg=75,
        note="x" * 201,
    )
    assert response.status_code == 422
    assert json_body(response)["errors"] == [{"field": "note", "code": "TOO_LONG"}]


async def test_put_accepts_a_note_at_exactly_200_characters(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    note = "x" * 200
    response = await _put_weight(
        client,
        registered["access_token"],
        measured_on=_today_cairo().isoformat(),
        weight_kg=75,
        note=note,
    )
    assert response.status_code == 200
    assert json_body(response)["entry"]["note"] == note


# --- PUT: the future check resolves through the caller's timezone, not UTC ----------------


async def test_measured_on_future_check_uses_the_callers_timezone_not_utc(
    client: AsyncClient,
) -> None:
    """This task's own "done when": a user east of UTC can log their own "today" even
    when UTC still calls it yesterday. Pacific/Kiritimati (UTC+14) is the most extreme
    real IANA zone -- chosen, like test_workout_sessions.py's own equivalent test, so
    the local calendar date is very often a day ahead of UTC's, exercising exactly the
    failure mode §4.2 describes for Africa/Cairo at 01:00, just with a wider (and
    therefore more reliably observed) divergence window.

    `today_local` is computed with the exact formula the server is specified to use;
    submitting it must always succeed for a correct implementation, whatever instant
    this test happens to run at -- a UTC-anchored bug would instead reject it
    whenever, at call time, Kiritimati's local date has already rolled over past
    UTC's (roughly 14 of every 24 hours).
    """
    registered = await _register_and_onboard(client)
    patched = await _patch_profile(
        client, registered["access_token"], {"timezone": "Pacific/Kiritimati"}
    )
    assert patched.status_code == 200

    today_local = datetime.now(UTC).astimezone(ZoneInfo("Pacific/Kiritimati")).date()
    response = await _put_weight(
        client, registered["access_token"], measured_on=today_local.isoformat(), weight_kg=75
    )
    assert response.status_code == 200, (
        "the caller's own local today must never be rejected as a future date"
    )


async def test_put_normalises_a_blank_note_to_null(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _put_weight(
        client,
        registered["access_token"],
        measured_on=_today_cairo().isoformat(),
        weight_kg=75,
        note="   ",
    )
    assert response.status_code == 200
    assert json_body(response)["entry"]["note"] is None


# --- PATCH /profile weight_kg -> upserts today's entry (P2-ADR-06, direction 2) -----------


async def test_patch_profile_weight_upserts_todays_entry(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo().isoformat()

    patched = await _patch_profile(client, registered["access_token"], {"weight_kg": 80})
    assert patched.status_code == 200
    assert json_body(patched)["profile"]["weight_kg"] == 80

    listed = await _get_weight(client, registered["access_token"])
    entries = json_body(listed)["entries"]
    assert {"measured_on": today, "weight_kg": 80} in entries


async def test_patch_profile_weight_replaces_an_existing_todays_entry(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo().isoformat()

    put = await _put_weight(client, registered["access_token"], measured_on=today, weight_kg=75)
    assert put.status_code == 200

    patched = await _patch_profile(client, registered["access_token"], {"weight_kg": 82})
    assert patched.status_code == 200

    listed = await _get_weight(client, registered["access_token"])
    entries = json_body(listed)["entries"]
    assert [e for e in entries if e["measured_on"] == today] == [
        {"measured_on": today, "weight_kg": 82}
    ]


async def test_patch_profile_weight_preserves_an_existing_note(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The one silent-data-loss trap this coupling invites: a routine Settings weight
    edit must never wipe a note the user already attached to today's PUT entry."""
    registered = await _register_and_onboard(client)
    user_id = uuid.UUID(registered["user"]["id"])
    today = _today_cairo()

    put = await _put_weight(
        client,
        registered["access_token"],
        measured_on=today.isoformat(),
        weight_kg=75,
        note="felt heavy today",
    )
    assert put.status_code == 200

    patched = await _patch_profile(client, registered["access_token"], {"weight_kg": 76})
    assert patched.status_code == 200

    entry = await _load_entry(db_session, user_id, today)
    assert entry is not None
    assert entry.weight_kg == 76
    assert entry.note == "felt heavy today", (
        "PATCH /profile's own weight write must never overwrite an existing note"
    )


async def test_patch_profile_clearing_weight_does_not_create_an_entry(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)

    patched = await _patch_profile(client, registered["access_token"], {"weight_kg": None})
    assert patched.status_code == 200
    assert json_body(patched)["profile"]["weight_kg"] is None

    listed = await _get_weight(client, registered["access_token"])
    assert json_body(listed)["entries"] == []


async def test_patch_profile_weight_logs_against_the_resulting_timezone(
    client: AsyncClient,
) -> None:
    """When a single PATCH changes both `timezone` and `weight_kg`, "today" must
    resolve through the NEW zone, not the one in effect before this request -- the
    same resulting_* convention assert_goal_permitted already uses for birth_date/goal.
    """
    registered = await _register_and_onboard(client)
    new_today = datetime.now(UTC).astimezone(ZoneInfo("Pacific/Kiritimati")).date()

    patched = await _patch_profile(
        client,
        registered["access_token"],
        {"timezone": "Pacific/Kiritimati", "weight_kg": 80},
    )
    assert patched.status_code == 200

    listed = await _get_weight(client, registered["access_token"], **{"to": new_today.isoformat()})
    entries = json_body(listed)["entries"]
    assert {"measured_on": new_today.isoformat(), "weight_kg": 80} in entries


# --- DELETE: rolls profiles.weight_kg back to the next newest -----------------------------


async def test_delete_the_newest_entry_rolls_profile_back_to_the_next_newest(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo()
    older = today - timedelta(days=5)

    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=older.isoformat(), weight_kg=80
        )
    ).status_code == 200
    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=today.isoformat(), weight_kg=75
        )
    ).status_code == 200

    profile_before = await _get_profile(client, registered["access_token"])
    assert json_body(profile_before)["profile"]["weight_kg"] == 75

    deleted = await _delete_weight(client, registered["access_token"], today.isoformat())
    assert deleted.status_code == 204
    assert deleted.content == b""

    profile_after = await _get_profile(client, registered["access_token"])
    assert json_body(profile_after)["profile"]["weight_kg"] == 80, (
        "deleting the newest entry must roll profiles.weight_kg back to the next newest"
    )


async def test_delete_the_only_entry_leaves_profile_weight_unchanged(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo().isoformat()

    assert (
        await _put_weight(client, registered["access_token"], measured_on=today, weight_kg=80)
    ).status_code == 200

    deleted = await _delete_weight(client, registered["access_token"], today)
    assert deleted.status_code == 204

    profile = await _get_profile(client, registered["access_token"])
    assert json_body(profile)["profile"]["weight_kg"] == 80, (
        "with no entry left to roll back to, profiles.weight_kg is left exactly as it was"
    )


async def test_delete_a_non_newest_entry_does_not_touch_profile_weight(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo()
    older = today - timedelta(days=5)

    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=older.isoformat(), weight_kg=80
        )
    ).status_code == 200
    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=today.isoformat(), weight_kg=75
        )
    ).status_code == 200

    deleted = await _delete_weight(client, registered["access_token"], older.isoformat())
    assert deleted.status_code == 204

    profile = await _get_profile(client, registered["access_token"])
    assert json_body(profile)["profile"]["weight_kg"] == 75


async def test_delete_unknown_measured_on_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _delete_weight(client, registered["access_token"], _today_cairo().isoformat())
    assert response.status_code == 404
    assert json_body(response)["code"] == "NOT_FOUND"


async def test_delete_malformed_measured_on_returns_404(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    response = await _delete_weight(client, registered["access_token"], "not-a-date")
    assert response.status_code == 404
    assert json_body(response)["code"] == "NOT_FOUND"


# --- GET: entries, sparse 7-day moving average, summary ------------------------------------


async def test_get_moving_average_is_sparse_until_three_points_fall_in_the_window(
    client: AsyncClient,
) -> None:
    """§5.10: "computed only where at least three entries exist in the window ...
    days with no entry are not interpolated." Seven consecutive daily entries,
    80 down to 74 by 1kg/day, ending today."""
    registered = await _register_and_onboard(client)
    today = _today_cairo()
    weights = [80, 79, 78, 77, 76, 75, 74]  # day-6 .. day-0 (today)

    for offset, weight in zip(range(6, -1, -1), weights, strict=True):
        measured_on = (today - timedelta(days=offset)).isoformat()
        assert (
            await _put_weight(
                client, registered["access_token"], measured_on=measured_on, weight_kg=weight
            )
        ).status_code == 200

    response = await _get_weight(client, registered["access_token"])
    assert response.status_code == 200
    body = json_body(response)
    assert len(body["entries"]) == 7

    by_date = {point["measured_on"]: point["weight_kg"] for point in body["moving_average_7d"]}

    def day(offset: int) -> str:
        return (today - timedelta(days=offset)).isoformat()

    # day-6 (1 point in window) and day-5 (2 points) are too sparse -- no average.
    assert day(6) not in by_date
    assert day(5) not in by_date
    # day-4: 80+79+78 / 3 = 79.0. day-0 (today): all seven / 7 = 77.0.
    assert by_date[day(4)] == 79.0
    assert by_date[day(3)] == 78.5
    assert by_date[day(2)] == 78.0
    assert by_date[day(1)] == 77.5
    assert by_date[day(0)] == 77.0


async def test_get_summary_reports_first_latest_change_and_count(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo()

    assert (
        await _put_weight(
            client,
            registered["access_token"],
            measured_on=(today - timedelta(days=10)).isoformat(),
            weight_kg=76.1,
        )
    ).status_code == 200
    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=today.isoformat(), weight_kg=73.4
        )
    ).status_code == 200

    response = await _get_weight(client, registered["access_token"])
    summary = json_body(response)["summary"]
    assert summary["first"] == 76.1
    assert summary["latest"] == 73.4
    assert summary["change_kg"] == -2.7
    assert summary["entry_count"] == 2


async def test_get_with_no_entries_returns_the_well_formed_empty_shape(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    response = await _get_weight(client, registered["access_token"])
    assert response.status_code == 200
    body = json_body(response)
    assert body == {
        "entries": [],
        "moving_average_7d": [],
        "summary": {"first": None, "latest": None, "change_kg": None, "entry_count": 0},
    }


async def test_get_default_range_excludes_entries_older_than_90_days(
    client: AsyncClient,
) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo()

    assert (
        await _put_weight(
            client, registered["access_token"], measured_on=today.isoformat(), weight_kg=75
        )
    ).status_code == 200
    assert (
        await _put_weight(
            client,
            registered["access_token"],
            measured_on=(today - timedelta(days=100)).isoformat(),
            weight_kg=90,
        )
    ).status_code == 200

    response = await _get_weight(client, registered["access_token"])
    entries = json_body(response)["entries"]
    dates = {e["measured_on"] for e in entries}
    assert today.isoformat() in dates
    assert (today - timedelta(days=100)).isoformat() not in dates


async def test_get_range_wider_than_730_days_is_clamped(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo()
    within_clamp = today - timedelta(days=100)
    beyond_clamp = today - timedelta(days=800)

    assert (
        await _put_weight(
            client,
            registered["access_token"],
            measured_on=within_clamp.isoformat(),
            weight_kg=75,
        )
    ).status_code == 200
    assert (
        await _put_weight(
            client,
            registered["access_token"],
            measured_on=beyond_clamp.isoformat(),
            weight_kg=90,
        )
    ).status_code == 200

    response = await _get_weight(
        client,
        registered["access_token"],
        **{"from": beyond_clamp.isoformat(), "to": today.isoformat()},
    )
    dates = {e["measured_on"] for e in json_body(response)["entries"]}
    assert within_clamp.isoformat() in dates
    assert beyond_clamp.isoformat() not in dates, (
        "a requested span over 730 days must be clamped from the older end"
    )


# --- Rate limit: 30 / hour per user, PUT only (§7.3) ----------------------------------------


async def test_put_rate_limit_applies_at_30_per_hour(client: AsyncClient) -> None:
    registered = await _register_and_onboard(client)
    today = _today_cairo()

    for offset in range(30):
        response = await _put_weight(
            client,
            registered["access_token"],
            measured_on=(today - timedelta(days=offset)).isoformat(),
            weight_kg=75,
        )
        assert response.status_code == 200

    refused = await _put_weight(
        client,
        registered["access_token"],
        measured_on=(today - timedelta(days=30)).isoformat(),
        weight_kg=75,
    )
    assert refused.status_code == 429
    assert json_body(refused)["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers


# --- Cross-tenant isolation ------------------------------------------------------------------


async def test_get_never_returns_another_users_entries(client: AsyncClient) -> None:
    owner = await _register_and_onboard(client)
    assert (
        await _put_weight(
            client, owner["access_token"], measured_on=_today_cairo().isoformat(), weight_kg=75
        )
    ).status_code == 200

    other = await _register_and_onboard(client)
    response = await _get_weight(client, other["access_token"])
    assert json_body(response)["entries"] == []


async def test_delete_cannot_reach_another_users_entry_by_the_same_date(
    client: AsyncClient,
) -> None:
    """DELETE's only identifier is the path `measured_on`, which
    test_cross_tenant.py's body-field scanner cannot see -- proven directly here,
    matching test_workout_sets.py's own placement of its P2-ADR-09-specific proof.
    Owner and intruder both address the identical calendar date; each user_id-scoped
    query resolves independently, so the intruder's call 404s on their own (absent)
    row rather than ever touching the owner's.
    """
    owner = await _register_and_onboard(client)
    today = _today_cairo().isoformat()
    assert (
        await _put_weight(client, owner["access_token"], measured_on=today, weight_kg=75)
    ).status_code == 200

    intruder = await _register_and_onboard(client)
    response = await _delete_weight(client, intruder["access_token"], today)
    assert response.status_code == 404
    assert response.status_code != 403

    still_there = await _get_weight(client, owner["access_token"])
    assert {"measured_on": today, "weight_kg": 75} in json_body(still_there)["entries"], (
        "an intruder's DELETE against a coincidentally-shared date must never reach "
        "the owner's own entry"
    )
