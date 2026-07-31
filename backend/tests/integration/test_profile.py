"""§5.7 (the profile half of GET /auth/me), §5.8 (POST /profile) and §5.9 (GET/PATCH
/profile), plus T-08's A.5 item 7 closure: onboarding_completed must be computed, not
hardcoded, everywhere the token-pair/`/auth/me` shape reports it.

Per the task's own testing rule, most tests here assert that a control prevents
something (a second POST, a minor selecting 'lose', a client-sent onboarding_completed,
cross-tenant access, the 30/hour limit) rather than only that the happy path works. The
`_isolated_rate_limiter` fixture mirrors every other integration test module in this
suite: /auth/register is 5/hour per IP, and every test here goes through it at least
once from the same test-client "IP" (ASGITransport reports no peer, so every test
shares one bucket without a reset).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.integrations import firebase
from app.models.audit import AuditLog

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_LOGIN = "/api/v1/auth/login"
_REFRESH = "/api/v1/auth/refresh"
_ME = "/api/v1/auth/me"
_PROFILE = "/api/v1/profile"
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


def _birth_date_years_ago(years: int) -> str:
    """A birth date `years` years before the real "today", computed at call time rather
    than hardcoded, so a minor/adult fixture stays correct however far in the future
    this suite is run -- unlike test_saf_age_goal.py's pinned P1-SAF-001 boundary tests,
    these integration tests exercise the route with `date.today()` as the server sees it.
    """
    today = date.today()
    try:
        return today.replace(year=today.year - years).isoformat()
    except ValueError:
        return today.replace(year=today.year - years, day=28).isoformat()


async def _register(client: AsyncClient, *, email: str | None = None) -> dict:
    response = await client.post(
        _REGISTER, json={"email": email or _unique_email(), "password": _PASSWORD}
    )
    assert response.status_code == 201
    return response.json()


async def _login(client: AsyncClient, *, email: str, password: str = _PASSWORD):
    return await client.post(_LOGIN, json={"email": email, "password": password})


async def _refresh(client: AsyncClient, *, refresh_token: str):
    return await client.post(_REFRESH, json={"refresh_token": refresh_token})


async def _me(client: AsyncClient, access_token: str):
    return await client.get(_ME, headers=_auth_headers(access_token))


def _profile_body(**overrides: object) -> dict:
    body: dict[str, object] = {
        "name": "Nabil",
        "gender": "male",
        "birth_date": _birth_date_years_ago(30),
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


async def _create_profile(client: AsyncClient, access_token: str, **overrides: object):
    return await client.post(
        _PROFILE, json=_profile_body(**overrides), headers=_auth_headers(access_token)
    )


async def _get_profile(client: AsyncClient, access_token: str):
    return await client.get(_PROFILE, headers=_auth_headers(access_token))


async def _patch_profile(client: AsyncClient, access_token: str, body: dict):
    return await client.patch(_PROFILE, json=body, headers=_auth_headers(access_token))


# --- POST /profile: happy-path shape, then the controls ----------------------------------


async def test_post_profile_returns_the_exact_201_shape(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _create_profile(client, registered["access_token"])

    assert response.status_code == 201
    body = response.json()
    assert body["profile"]["onboarding_completed"] is True
    assert body["profile"]["name"] == "Nabil"
    assert body["profile"]["goal"] == "maintain"
    assert body["derived"]["age"] == 30


async def test_a_second_post_profile_is_rejected(client: AsyncClient) -> None:
    """§5.8: "enforced by the primary key rather than by application politeness" --
    the control this endpoint exists to provide.
    """
    registered = await _register(client)
    access_token = registered["access_token"]

    first = await _create_profile(client, access_token)
    assert first.status_code == 201

    second = await _create_profile(client, access_token, name="Someone Else")
    assert second.status_code == 409
    assert second.json()["code"] == "PROFILE_ALREADY_EXISTS"


async def test_post_profile_writes_the_profile_created_audit_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    user_id = uuid.UUID(registered["user"]["id"])

    response = await _create_profile(client, registered["access_token"])
    assert response.status_code == 201

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "profile.created", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].entity == "profile"
    assert rows[0].entity_id == user_id


async def test_minor_is_blocked_from_goal_lose_on_post(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _create_profile(
        client, registered["access_token"], birth_date=_birth_date_years_ago(15), goal="lose"
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "GOAL_NOT_PERMITTED_FOR_MINOR"
    assert "maintain" in body["detail"]
    assert "gain" in body["detail"]


async def test_minor_may_still_select_maintain_or_gain_on_post(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _create_profile(
        client, registered["access_token"], birth_date=_birth_date_years_ago(15), goal="gain"
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    ("overrides", "expected_field"),
    [
        ({"name": "N"}, "name"),
        ({"name": "Nabil123"}, "name"),
        ({"gender": "other"}, "gender"),
        ({"birth_date": "not-a-date"}, "birth_date"),
        ({"birth_date": "2999-01-01"}, "birth_date"),  # in the future
        ({"height_cm": 99}, "height_cm"),
        ({"height_cm": 251}, "height_cm"),
        ({"weight_kg": 29}, "weight_kg"),
        ({"weight_kg": 301}, "weight_kg"),
        ({"goal": "bulk"}, "goal"),
        ({"experience_level": "expert"}, "experience_level"),
        ({"activity_level": "extreme"}, "activity_level"),
        ({"unit_system": "furlongs"}, "unit_system"),
        ({"language": "fr"}, "language"),
    ],
)
async def test_post_profile_rejects_each_out_of_range_or_disallowed_field(
    client: AsyncClient, overrides: dict, expected_field: str
) -> None:
    """§7.1's per-field rules -- each one is a control on its own, not just a shape
    check, so every field gets its own case rather than one test asserting the schema
    "looks right".
    """
    registered = await _register(client)
    response = await _create_profile(client, registered["access_token"], **overrides)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert any(error["field"] == expected_field for error in body["errors"])


async def test_concurrent_double_post_profile_leaves_exactly_one_winner(
    client: AsyncClient,
) -> None:
    """§5.8: "enforced by the primary key rather than by application politeness." The
    pre-check in profile_service gives a fast 409 in the common case, but only the
    profiles.user_id PRIMARY KEY guarantees this under a genuine race -- two requests
    that both pass the pre-check before either has committed. Fired concurrently so both
    reach the INSERT before either commits, the same shape as the reset-code concurrent-
    redemption control elsewhere in this suite's spec.
    """
    registered = await _register(client)
    access_token = registered["access_token"]

    responses = await asyncio.gather(
        _create_profile(client, access_token, name="First"),
        _create_profile(client, access_token, name="Second"),
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [201, 409]


# --- GET /profile --------------------------------------------------------------------------


async def test_get_profile_before_onboarding_is_404(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _get_profile(client, registered["access_token"])
    assert response.status_code == 404
    assert response.json()["code"] == "PROFILE_NOT_FOUND"


async def test_get_profile_returns_the_created_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]
    await _create_profile(client, access_token, name="Nabil")

    response = await _get_profile(client, access_token)
    assert response.status_code == 200
    assert response.json()["profile"]["name"] == "Nabil"


# --- PATCH /profile: the editable/immutable table (§5.9) and its controls ------------------


async def test_patch_profile_before_onboarding_is_404(client: AsyncClient) -> None:
    registered = await _register(client)
    response = await _patch_profile(client, registered["access_token"], {"goal": "gain"})
    assert response.status_code == 404
    assert response.json()["code"] == "PROFILE_NOT_FOUND"


async def test_patch_profile_rejects_an_empty_body(client: AsyncClient) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]
    await _create_profile(client, access_token)

    response = await _patch_profile(client, access_token, {})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_patch_profile_updates_only_the_fields_present_in_the_body(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]
    # unit_system deliberately not left at its own default ("metric"), so the assertion
    # below proves the field was left alone rather than merely matching by coincidence.
    await _create_profile(client, access_token, goal="maintain", unit_system="imperial")

    response = await _patch_profile(client, access_token, {"goal": "gain"})
    assert response.status_code == 200
    body = response.json()["profile"]
    assert body["goal"] == "gain"
    assert body["unit_system"] == "imperial"  # untouched


async def test_patch_client_sent_onboarding_completed_does_not_take_effect(
    client: AsyncClient,
) -> None:
    """§5.9: "Server-controlled. A client sending it is ignored, not rejected." Sent
    alongside a real field change so the request is not merely an empty-body no-op --
    the control under test is that the false value has no effect, not that the request
    is accepted at all.
    """
    registered = await _register(client)
    access_token = registered["access_token"]
    await _create_profile(client, access_token)

    response = await _patch_profile(
        client, access_token, {"goal": "gain", "onboarding_completed": False}
    )
    assert response.status_code == 200
    body = response.json()["profile"]
    assert body["goal"] == "gain"
    assert body["onboarding_completed"] is True


async def test_minor_is_blocked_from_goal_lose_on_patch_when_goal_changes(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]
    await _create_profile(
        client, access_token, birth_date=_birth_date_years_ago(15), goal="maintain"
    )

    response = await _patch_profile(client, access_token, {"goal": "lose"})
    assert response.status_code == 422
    assert response.json()["code"] == "GOAL_NOT_PERMITTED_FOR_MINOR"


async def test_minor_is_blocked_from_goal_lose_on_patch_when_only_birth_date_changes(
    client: AsyncClient,
) -> None:
    """The merge case: `goal` itself is not in this PATCH body at all, but re-applying
    P1-SAF-001 against the *resulting* state (existing goal='lose' + new, younger
    birth_date) must still block it -- proving the check re-evaluates the merged
    profile, not just whichever field the request happened to touch.
    """
    registered = await _register(client)
    access_token = registered["access_token"]
    # Adult with 'lose' is permitted at creation.
    await _create_profile(client, access_token, birth_date=_birth_date_years_ago(30), goal="lose")

    response = await _patch_profile(client, access_token, {"birth_date": _birth_date_years_ago(15)})
    assert response.status_code == 422
    assert response.json()["code"] == "GOAL_NOT_PERMITTED_FOR_MINOR"


async def test_patch_gender_and_birth_date_are_audited_with_before_and_after(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]
    user_id = uuid.UUID(registered["user"]["id"])
    original_birth_date = _birth_date_years_ago(30)
    new_birth_date = _birth_date_years_ago(31)
    await _create_profile(client, access_token, gender="male", birth_date=original_birth_date)

    response = await _patch_profile(
        client, access_token, {"gender": "female", "birth_date": new_birth_date}
    )
    assert response.status_code == 200

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "profile.updated", AuditLog.actor_user_id == user_id
            )
        )
    ).scalar_one()
    assert row.event_metadata["gender"] == {"before": "male", "after": "female"}
    assert row.event_metadata["birth_date"] == {
        "before": original_birth_date,
        "after": new_birth_date,
    }


async def test_patch_without_gender_or_birth_date_writes_no_audit_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]
    user_id = uuid.UUID(registered["user"]["id"])
    await _create_profile(client, access_token)

    response = await _patch_profile(client, access_token, {"goal": "gain"})
    assert response.status_code == 200

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "profile.updated", AuditLog.actor_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


# --- Cross-tenant: another user's profile is unreachable ----------------------------------


async def test_another_users_profile_is_unreachable_through_get_or_patch(
    client: AsyncClient,
) -> None:
    user_a = await _register(client)
    token_a = user_a["access_token"]
    await _create_profile(client, token_a, name="User A", goal="maintain")

    user_b = await _register(client)
    token_b = user_b["access_token"]

    # B has no profile of their own -- 404, never A's data, regardless of what exists
    # elsewhere in the table. No endpoint accepts a profile id from the client; the
    # bearer token is the only thing that ever selects a row.
    get_as_b = await _get_profile(client, token_b)
    assert get_as_b.status_code == 404

    patch_as_b = await _patch_profile(client, token_b, {"goal": "gain"})
    assert patch_as_b.status_code == 404

    # B can create their own, independently of A's already existing.
    create_as_b = await _create_profile(client, token_b, name="User B", goal="lose")
    assert create_as_b.status_code == 201

    # A's row is untouched by any of the above.
    get_as_a = await _get_profile(client, token_a)
    assert get_as_a.json()["profile"]["name"] == "User A"
    assert get_as_a.json()["profile"]["goal"] == "maintain"


# --- §6.4: 30/hour per user -----------------------------------------------------------------


async def test_profile_is_rate_limited_at_30_per_hour_per_user(client: AsyncClient) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]

    create_response = await _create_profile(client, access_token)  # consumes 1 of 30
    assert create_response.status_code == 201

    for _ in range(29):
        response = await _get_profile(client, access_token)
        assert response.status_code == 200

    refused = await _get_profile(client, access_token)
    assert refused.status_code == 429
    body = refused.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in refused.headers
    retry_after = int(refused.headers["Retry-After"])
    assert 1 <= retry_after <= 3600


# --- GET /auth/me: the exact §5.7 shape -----------------------------------------------------


async def test_auth_me_returns_null_profile_and_false_before_onboarding(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    response = await _me(client, registered["access_token"])

    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_completed"] is False
    assert body["profile"] is None
    assert body["user"]["email"] == registered["user"]["email"]
    assert body["user"]["auth_methods"] == ["password"]
    assert "email_verified" in body["user"]
    assert "created_at" in body["user"]


async def test_auth_me_returns_the_profile_and_true_after_onboarding(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    access_token = registered["access_token"]
    await _create_profile(client, access_token, name="Nabil")

    response = await _me(client, access_token)
    body = response.json()
    assert body["onboarding_completed"] is True
    assert body["profile"]["name"] == "Nabil"


async def test_auth_me_lists_password_then_linked_social_providers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5.7's own example: `"auth_methods": ["password","google"]`."""
    email = _unique_email()
    registered = await _register(client, email=email)
    access_token = registered["access_token"]

    monkeypatch.setattr(
        firebase,
        "verify_id_token",
        lambda id_token: {
            "uid": "firebase-uid-link-1",
            "email_verified": True,
            "email": email,
            "firebase": {
                "sign_in_provider": "google.com",
                "identities": {"google.com": ["google-uid-link-1"]},
            },
        },
    )
    link_response = await client.post("/api/v1/auth/social/google", json={"id_token": "t"})
    assert link_response.status_code == 200
    assert link_response.json()["is_new_user"] is False

    response = await _me(client, access_token)
    assert response.json()["user"]["auth_methods"] == ["password", "google"]


# --- A.5 item 7: onboarding_completed is computed everywhere it is reported ----------------


async def test_onboarding_completed_flips_true_in_auth_me_login_and_refresh(
    client: AsyncClient,
) -> None:
    """Closes A.5 item 7: register/login and, independently, refresh() both used to
    hardcode `onboarding_completed=False`. This walks one account through all three
    surfaces before and after completing onboarding -- refresh() in particular needed
    its own fix (it builds its own IssuedSession rather than going through
    _issue_session), so it gets an explicit before/after check here rather than only
    register and login.
    """
    email = _unique_email()
    registered = await _register(client, email=email)
    access_token = registered["access_token"]
    refresh_token = registered["refresh_token"]

    assert registered["user"]["onboarding_completed"] is False

    me_before = await _me(client, access_token)
    assert me_before.json()["onboarding_completed"] is False

    login_before = await _login(client, email=email)
    assert login_before.json()["user"]["onboarding_completed"] is False

    refresh_before = await _refresh(client, refresh_token=refresh_token)
    assert refresh_before.status_code == 200
    assert refresh_before.json()["user"]["onboarding_completed"] is False
    refresh_token_2 = refresh_before.json()["refresh_token"]

    create_response = await _create_profile(client, access_token)
    assert create_response.status_code == 201

    me_after = await _me(client, access_token)
    assert me_after.json()["onboarding_completed"] is True

    login_after = await _login(client, email=email)
    assert login_after.json()["user"]["onboarding_completed"] is True

    refresh_after = await _refresh(client, refresh_token=refresh_token_2)
    assert refresh_after.status_code == 200
    assert refresh_after.json()["user"]["onboarding_completed"] is True
