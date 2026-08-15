"""§11.1's security row, §11.3 item 3, §12 T-09's own instruction: "enumerate the route
table programmatically ... do not hand-write the list, or a route added later escapes
it." §6.5: another user's resource must come back as a generic 404, never a 403.

Route discovery, all of it, comes from the live app (`_enumerate_api_routes`), not a
literal path list -- adding a route later gets it classified automatically. What is
hand-maintained is `_OWN_RESOURCE_FIELDS`: the reviewed set of request-body field names
that hold the caller's own content rather than a reference to someone else's row. Any
field NOT in that set is treated as a candidate identifier and gets parametrized into
`test_user_b_cannot_use_user_as_identifier_on_a_reference_field` below; if a future
field's real name isn't taught to `_identifier_value_for`, that case fails loudly by
`KeyError` instead of silently passing. That is what keeps "a route added later" from
escaping the matrix even though this file cannot literally hand-write the future.

This application's own architecture (§3: "every repository function that reads
user-owned data takes user_id as a mandatory first argument"; no route anywhere accepts
a path or query parameter naming another user's resource) means only one field, across
every user-scoped route in Phase 1, actually names a specific other row:
`LogoutRequest.refresh_token`. The other six user-scoped routes take no such field at
all -- "whose data" is entirely a function of the bearer token, never of anything an
attacker could put in the request -- so cross-tenant isolation for those six is proven
the only way that is meaningful when there is nothing to substitute: call the route as
user B and show user A's row is never read out or written to, by direct comparison
against a real user A who has real, distinguishing data.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from datetime import date

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_active
from app.core.rate_limit import limiter
from app.database import set_rls_user
from app.main import create_app
from app.models.profile import Profile
from app.models.user import User
from tests.support import JSONDict, json_body

# asyncio_mode = "auto" (pyproject.toml) collects async def tests without a marker; no
# module-level pytestmark here because, unlike every other integration test file, this
# one also has plain sync tests (the route-enumeration canaries below).

_REGISTER = "/api/v1/auth/register"
_ME = "/api/v1/auth/me"
_PROFILE = "/api/v1/profile"
_ACCOUNT = "/api/v1/account"
_LOGOUT = "/api/v1/auth/logout"
_LOGOUT_ALL = "/api/v1/auth/logout-all"
_REFRESH = "/api/v1/auth/refresh"
_PASSWORD = "correct horse battery"

# A fresh app instance purely for route introspection -- create_app() only registers
# routes and middleware, never touches the database or Firebase (both live in the
# lifespan handler, per A.5 items 10 and 15), so this is safe to build at import time
# and does not need the `client` fixture's ASGI transport.
_ROUTE_APP = create_app()


@pytest.fixture(autouse=True)
def _isolated_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


# --- route enumeration (do not hand-write the list) ---------------------------------------


def _enumerate_api_routes() -> list[APIRoute]:
    """Every route FastAPI actually serves, found by walking the live app.

    FastAPI's `include_router` defers resolution behind a private `_IncludedRouter`
    wrapper whose `original_router` holds the real `APIRouter` (confirmed against the
    installed fastapi version; this is the one part of this file coupled to FastAPI's
    internals rather than its public contract). Walked recursively so nesting one
    include_router beneath another still resolves, and falls back to finding nothing
    silently only if FastAPI's internals move again -- which
    `test_route_enumeration_finds_the_documented_catalogue` exists to catch.
    """
    routes: list[APIRoute] = []

    def _walk(candidates: Iterable[object]) -> None:
        for route in candidates:
            if isinstance(route, APIRoute):
                routes.append(route)
            elif hasattr(route, "original_router"):
                _walk(route.original_router.routes)

    _walk(_ROUTE_APP.routes)
    return routes


def _is_user_scoped(route: APIRoute) -> bool:
    """True when resolving this route depends on `require_active` anywhere in its
    dependency tree -- the one seam (app/core/dependencies.py) where the app decides
    "which user" from the bearer token. Walked recursively, not just
    `route.dependant.dependencies` directly, because app/routers/profile.py wraps it
    one level down in `_rate_limited_user` (its own rate-limit key needs the resolved
    user before the route body runs).
    """

    def _walk(dependant: Dependant, seen: set[int]) -> bool:
        if id(dependant) in seen:
            return False
        seen.add(id(dependant))
        if dependant.call is require_active:
            return True
        return any(_walk(sub, seen) for sub in dependant.dependencies)

    return _walk(route.dependant, set())


# Reviewed request-body field names that hold the caller's own content, not a reference
# to another user's row (app/schemas/auth.py, app/schemas/profile.py,
# app/routers/account.py, checked by hand against every user-scoped route as of this
# file's writing). A field NOT in this set is a candidate cross-tenant identifier.
_OWN_RESOURCE_FIELDS = {
    "password",  # DeleteAccountRequest -- the caller's own credential, not a reference
    "name",
    "gender",
    "birth_date",
    "height_cm",
    "weight_kg",
    "goal",
    "experience_level",
    "activity_level",
    "unit_system",
    "language",
    "onboarding_completed",  # Profile{Create,Update}Request -- scalar content fields
    "days_per_week",  # T-17: ProgramGenerateRequest -- a count the caller chooses for
    # their own plan, not a reference to anyone else's row; program_service resolves
    # the rest of generation entirely from the caller's own profile (§6.1's PlanInput
    # is built server-side from the authenticated user's profile, never from the body).
    "timezone",  # T-18: ProfileUpdateRequest -- an IANA name describing the caller's
    # own clock, not a reference to another row (validated against
    # zoneinfo.available_timezones(), a fixed set with no per-user ownership).
    "notes",  # T-18: WorkoutFinishRequest -- free text about the caller's own session,
    # not a reference to anyone else's row.
    "exercise_id",  # T-19: WorkoutSetCreateRequest -- exercises are public reference
    # data with no owner (P2-ADR-09's stated exception, §4.10): every onboarded user
    # can legitimately log a set against any active exercise id, so there is no "other
    # user's exercise" for this field to steal.
    "reps",
    "rpe",
    "is_warmup",  # T-19: WorkoutSet{Create,Patch}Request -- the caller's own set
    # content, not a reference to anyone else's row. (weight_kg already reviewed above.)
    "measured_on",  # T-20: BodyWeightUpsertRequest -- the calendar day the caller is
    # logging against, not a reference to anyone else's row; body_weight_entries has no
    # cross-user addressing at all (UNIQUE per (user_id, measured_on), §4.8).
    "note",  # T-20: BodyWeightUpsertRequest -- free text about the caller's own entry,
    # not a reference to anyone else's row. (weight_kg already reviewed above.)
}


def _reference_fields(route: APIRoute) -> set[str]:
    """Request-body field names on `route` not reviewed as the caller's own content --
    candidates for a cross-tenant identifier-substitution case."""
    body_field = route.body_field
    if body_field is None:
        return set()
    model = body_field.field_info.annotation
    field_names: set[str] = set(getattr(model, "model_fields", {}))
    return field_names - _OWN_RESOURCE_FIELDS


def _route_key(route: APIRoute) -> tuple[str, str]:
    assert route.methods is not None
    (method,) = route.methods
    return method, route.path


def test_route_enumeration_finds_the_documented_catalogue() -> None:
    """Canary for `_enumerate_api_routes` itself: Phase 1's §5.1 catalogue had 15 rows
    (14 API endpoints plus /health); T-16 (spec §5.1/§5.2) adds GET /exercises and
    GET /exercises/{id}, for 17; T-17 (§5.3-5.5) adds POST /program/generate,
    GET /program and GET /program/days/{day_id}, for 20; T-18 (§5.6/§5.8) adds
    POST /workouts, GET /workouts/active, POST /workouts/{id}/finish and
    POST /workouts/{id}/abandon, for 24; T-19 (§5.7) adds POST, PATCH and DELETE
    /workouts/{id}/sets[/{set_id}], for 27; T-20 (§5.10) adds PUT, GET and DELETE
    /body-weight[/{measured_on}], for 30. If a future FastAPI version changes how
    `include_router` wires routes again, this fails immediately instead of the matrix
    below silently running zero cases.
    """
    routes = _enumerate_api_routes()
    found = sorted(_route_key(r) for r in routes)
    assert len(routes) == 30, f"expected 30 routes per spec §5.1, found {len(routes)}: {found}"


def test_user_scoped_classification_matches_the_reviewed_reference_field_sets() -> None:
    """Reports the matrix's own shape and pins it against drift: the exact set of
    user-scoped routes, and the exact reference-field set found on each, must match
    what was reviewed when this file was written. A route becoming (or ceasing to be)
    user-scoped, or a reference field appearing on one that had none, fails this test
    by name -- forcing a conscious update here rather than a silent gap in coverage.
    """
    routes = _enumerate_api_routes()
    user_scoped = {_route_key(r): r for r in routes if _is_user_scoped(r)}

    expected_reference_fields: dict[tuple[str, str], frozenset[str]] = {
        ("GET", "/auth/me"): frozenset(),
        ("POST", "/profile"): frozenset(),
        ("GET", "/profile"): frozenset(),
        ("PATCH", "/profile"): frozenset(),
        ("DELETE", "/account"): frozenset(),
        ("POST", "/auth/logout"): frozenset({"refresh_token"}),
        ("POST", "/auth/logout-all"): frozenset(),
        # T-16: both depend on require_completed_profile, which itself depends on
        # require_active -- authenticated the same way every other user-scoped route
        # is. Neither takes a body (GET/path-param only), so neither has a reference
        # field: the exercise a caller can reach is a function of the id in the path,
        # never of anything naming another user's row (exercises has no owner at all).
        ("GET", "/exercises"): frozenset(),
        ("GET", "/exercises/{exercise_id}"): frozenset(),
        # T-17: POST /program/generate's only body field is days_per_week, reviewed
        # into _OWN_RESOURCE_FIELDS above (a count, not a reference). GET /program
        # takes no body or path parameter at all. GET /program/days/{day_id} takes no
        # body either, but -- unlike GET /exercises/{exercise_id} -- its path
        # parameter *does* name an owned row (a program_days id, owned via the parent
        # chain, P2-ADR-09): this scanner only inspects body fields, so that risk is
        # not caught by the identifier-substitution matrix below at all. It is proven
        # directly instead, both here
        # (test_get_program_day_belonging_to_another_user_returns_404) and again in
        # tests/integration/test_program.py's own fuller version of the same case.
        ("POST", "/program/generate"): frozenset(),
        ("GET", "/program"): frozenset(),
        ("GET", "/program/days/{day_id}"): frozenset(),
        # T-18: POST /workouts's program_day_id names another user's program_day the
        # same way POST /program/generate's days_per_week does not -- §5.6 states the
        # 404 explicitly ("if the program_day_id belongs to another user's program"),
        # so this is a second live identifier-substitution case below, not proven only
        # by direct comparison. GET /workouts/active takes no body or path parameter.
        # POST .../finish and .../abandon take a path `session_id` this scanner cannot
        # see (the same body-field blind spot as GET /program/days/{day_id} above) --
        # proven directly instead, in tests/integration/test_workout_sessions.py
        # (test_finish_on_another_users_session_returns_404 and its abandon
        # counterpart). `finish`'s only body field, `notes`, is reviewed into
        # _OWN_RESOURCE_FIELDS above.
        ("POST", "/workouts"): frozenset({"program_day_id"}),
        ("GET", "/workouts/active"): frozenset(),
        ("POST", "/workouts/{session_id}/finish"): frozenset(),
        ("POST", "/workouts/{session_id}/abandon"): frozenset(),
        # T-19: all three take only `exercise_id`/`reps`/`weight_kg`/`rpe`/`is_warmup`,
        # all reviewed into _OWN_RESOURCE_FIELDS above -- none of them names another
        # user's row. Their real cross-tenant risk is the path parameters this scanner
        # cannot see (`session_id`, and `set_id` on PATCH/DELETE -- workout_sets has no
        # user_id of its own at all, P2-ADR-09), proven directly instead in
        # tests/integration/test_workout_sets.py, including a direct RLS-level proof
        # that a set in another user's session is invisible even by its own id (that
        # task's own explicit requirement), not merely that the API's ownership check
        # 404s it.
        ("POST", "/workouts/{session_id}/sets"): frozenset(),
        ("PATCH", "/workouts/{session_id}/sets/{set_id}"): frozenset(),
        ("DELETE", "/workouts/{session_id}/sets/{set_id}"): frozenset(),
        # T-20: PUT /body-weight's fields (measured_on, weight_kg, note) are all
        # reviewed into _OWN_RESOURCE_FIELDS above -- body_weight_entries has no
        # cross-user addressing at all (UNIQUE per (user_id, measured_on)), so there is
        # no "another user's entry" for any of them to name. GET /body-weight takes
        # only query params, no body. DELETE /body-weight/{measured_on} takes a path
        # parameter this scanner cannot see (the same blind spot as GET
        # /program/days/{day_id} and the workout-sets routes above) -- proven directly
        # instead in tests/integration/test_body_weight.py
        # (test_delete_cannot_reach_another_users_entry_by_the_same_date), which also
        # proves GET's own isolation by direct comparison.
        ("PUT", "/body-weight"): frozenset(),
        ("GET", "/body-weight"): frozenset(),
        ("DELETE", "/body-weight/{measured_on}"): frozenset(),
    }

    assert set(user_scoped) == set(expected_reference_fields), (
        f"user-scoped route set changed: found {sorted(user_scoped)}, "
        f"expected {sorted(expected_reference_fields)}. Add or remove its cross-tenant "
        "case in this file before this test can pass."
    )
    for key, route in user_scoped.items():
        found_fields = frozenset(_reference_fields(route))
        assert found_fields == expected_reference_fields[key], (
            f"{key}: reference-field set is now {sorted(found_fields)}, expected "
            f"{sorted(expected_reference_fields[key])}. Update _OWN_RESOURCE_FIELDS and "
            "this file's cross-tenant case for it."
        )

    # Of 30 enumerated routes, 8 are unauthenticated by design (register, login, social
    # sign-in, refresh, the three password-reset calls, and health) and are scoped, if
    # at all, by a submitted email/token under their own §7.3 error contract rather than
    # by a bearer identity -- not this matrix's concern. The remaining 22 are user-scoped;
    # of those, 20 accept no field that could name another user's resource at all (the
    # only "identifier" is the bearer token itself, a reviewed own-content field, or --
    # for the T-16/T-17/T-18/T-19/T-20 GET-and-path-id routes -- a path id), and are
    # instead each proven isolated by their own test below; 2 (POST /auth/logout's
    # refresh_token and POST /workouts's program_day_id) do name another row and are the
    # live identifier-substitution cases.
    assert len(routes) == 30
    assert len(user_scoped) == 22


def _reference_field_cases() -> list[tuple[str, str, str]]:
    """(method, path, field) for every reference field this run's enumeration finds --
    computed from the live route table, not hand-listed, so a new field on an existing
    (or new) user-scoped route is picked up as a new parametrized case automatically."""
    cases = []
    for route in _enumerate_api_routes():
        if not _is_user_scoped(route):
            continue
        method, path = _route_key(route)
        for field in sorted(_reference_fields(route)):
            cases.append((method, path, field))
    return cases


# --- shared setup -------------------------------------------------------------------------


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def _register(client: AsyncClient, *, email: str | None = None) -> JSONDict:
    response = await client.post(
        _REGISTER, json={"email": email or _unique_email(), "password": _PASSWORD}
    )
    assert response.status_code == 201
    return json_body(response)


def _profile_body(**overrides: object) -> JSONDict:
    body: JSONDict = {
        "name": "Distinguishing Name",
        "gender": "male",
        "birth_date": date.today().replace(year=date.today().year - 30).isoformat(),
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


async def _get_profile(client: AsyncClient, access_token: str) -> Response:
    return await client.get(_PROFILE, headers=_auth_headers(access_token))


async def _patch_profile(client: AsyncClient, access_token: str, body: JSONDict) -> Response:
    return await client.patch(_PROFILE, json=body, headers=_auth_headers(access_token))


async def _me(client: AsyncClient, access_token: str) -> Response:
    return await client.get(_ME, headers=_auth_headers(access_token))


async def _delete_account(
    client: AsyncClient, access_token: str, *, password: str | None = _PASSWORD
) -> Response:
    body: JSONDict = {"password": password} if password is not None else {}
    return await client.request("DELETE", _ACCOUNT, json=body, headers=_auth_headers(access_token))


async def _logout(client: AsyncClient, access_token: str, refresh_token: str) -> Response:
    return await client.post(
        _LOGOUT, json={"refresh_token": refresh_token}, headers=_auth_headers(access_token)
    )


async def _logout_all(client: AsyncClient, access_token: str) -> Response:
    return await client.post(_LOGOUT_ALL, headers=_auth_headers(access_token))


async def _refresh(client: AsyncClient, refresh_token: str) -> Response:
    return await client.post(_REFRESH, json={"refresh_token": refresh_token})


async def _load_user(db_session: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db_session.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


async def _load_profile(db_session: AsyncSession, user_id: uuid.UUID) -> Profile | None:
    # profiles is FORCE-RLS; reading a row this test itself created for that same user
    # is legitimate (this is exactly how the app would read it for that user), not a
    # bypass -- see app/database.py's set_rls_user docstring.
    await set_rls_user(db_session, str(user_id))
    result = await db_session.execute(select(Profile).where(Profile.user_id == user_id))
    return result.scalar_one_or_none()


# --- the one live identifier-substitution case: POST /auth/logout's refresh_token ---------


async def _identifier_value_for(client: AsyncClient, field: str, *, user_a: JSONDict) -> str:
    """The real value belonging to "the other user" (`user_a`) for a given reference
    field.

    Deliberately a lookup, not a generic fabrication: a future reference field this
    file has not been taught to source raises KeyError, which fails its parametrized
    case loudly rather than silently passing an untested substitution.
    """
    if field == "refresh_token":
        return str(user_a["refresh_token"])
    if field == "program_day_id":
        # T-18: needs a real program_day_id owned by user_a -- onboard and generate a
        # plan for them first, the same setup test_workout_sessions.py's own
        # another-user's-program-day case uses.
        onboarded = await _onboard(client, user_a["access_token"])
        assert onboarded.status_code == 201
        generated = await _generate(client, user_a["access_token"])
        assert generated.status_code == 201
        day_id = json_body(generated)["program"]["days"][0]["id"]
        return str(day_id)
    raise KeyError(field)


@pytest.mark.parametrize("method,path,field", _reference_field_cases())
async def test_user_b_cannot_use_user_as_identifier_on_a_reference_field(
    client: AsyncClient, method: str, path: str, field: str
) -> None:
    """§6.5: another user's resource is a generic failure, never a 403 -- and, the
    invariant that actually matters, never a successful cross-tenant mutation.

    For `POST /auth/logout`, the correct outcome per §5.5/§7.3's own token-error
    contract is 401 TOKEN_INVALID, not 404: this endpoint has no path- or query-level
    resource id for §6.5's "confirm nothing about existence" 404 rule to apply to --
    the refresh token itself IS the credential being validated, and an unrecognised-or-
    foreign token has its own well-defined error family (401), the same as an expired
    or reused one. What this test actually enforces, and the part that would fail if
    the ownership check in auth_service.logout were ever dropped, is: never 403, never
    a 2xx, and user A's own session survives a stranger presenting its token to *their*
    authenticated logout call.
    """
    user_a = await _register(client)
    user_b = await _register(client)
    # Every user-scoped case below this file has reviewed requires a completed profile
    # (require_completed_profile, per T-16/T-17/T-18) except POST /auth/logout, which
    # onboarding never affects either way -- onboarding user_b unconditionally keeps
    # this one case generic instead of branching per route.
    onboard_b = await _onboard(client, user_b["access_token"])
    assert onboard_b.status_code == 201

    identifier = await _identifier_value_for(client, field, user_a=user_a)
    body = {field: identifier}

    response = await client.request(
        method, f"/api/v1{path}", json=body, headers=_auth_headers(user_b["access_token"])
    )

    assert response.status_code != 403, response.text
    assert response.status_code not in (200, 201, 202, 204), (
        f"user B's request against user A's {field!r} must not succeed: {response.text}"
    )
    assert response.status_code in (401, 404), response.text

    # The invariant that matters: A's own session must still be alive. If B's call had
    # actually revoked A's family, this refresh would now fail with TOKEN_INVALID.
    still_alive = await _refresh(client, user_a["refresh_token"])
    assert still_alive.status_code == 200, (
        "user A's refresh token family was revoked by user B's cross-tenant attempt"
    )


# --- the six routes with no reference field: proven isolated by direct comparison ---------


async def test_get_auth_me_never_returns_user_as_data(client: AsyncClient) -> None:
    user_a = await _register(client)
    onboard = await _onboard(client, user_a["access_token"], name="User A Distinguishing")
    assert onboard.status_code == 201

    user_b = await _register(client)
    response = await _me(client, user_b["access_token"])
    assert response.status_code == 200

    body = json_body(response)
    assert body["user"]["email"] == user_b["user"]["email"]
    assert body["user"]["email"] != user_a["user"]["email"]
    assert body["profile"] is None, "user B has not onboarded; must never see user A's profile"


async def test_get_profile_never_returns_user_as_profile(client: AsyncClient) -> None:
    user_a = await _register(client)
    onboard = await _onboard(client, user_a["access_token"], name="User A Distinguishing")
    assert onboard.status_code == 201

    user_b = await _register(client)
    response = await _get_profile(client, user_b["access_token"])

    # User B has no profile of their own -- the correct 404 is theirs, not a leak of A's.
    assert response.status_code == 404
    assert response.status_code != 403
    assert "User A Distinguishing" not in response.text


async def test_post_profile_never_touches_user_as_profile(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_a = await _register(client)
    onboard_a = await _onboard(client, user_a["access_token"], name="User A Distinguishing")
    assert onboard_a.status_code == 201
    profile_a_before = await _load_profile(db_session, uuid.UUID(user_a["user"]["id"]))
    assert profile_a_before is not None

    user_b = await _register(client)
    onboard_b = await _onboard(client, user_b["access_token"], name="User B Own Name")
    assert onboard_b.status_code == 201

    profile_a_after = await _load_profile(db_session, uuid.UUID(user_a["user"]["id"]))
    assert profile_a_after is not None
    assert profile_a_after.name == profile_a_before.name == "User A Distinguishing"

    profile_b = await _load_profile(db_session, uuid.UUID(user_b["user"]["id"]))
    assert profile_b is not None
    assert profile_b.name == "User B Own Name"


async def test_patch_profile_never_touches_user_as_profile(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_a = await _register(client)
    onboard_a = await _onboard(client, user_a["access_token"], name="User A Distinguishing")
    assert onboard_a.status_code == 201

    user_b = await _register(client)
    onboard_b = await _onboard(client, user_b["access_token"], name="User B Own Name")
    assert onboard_b.status_code == 201

    patched = await _patch_profile(client, user_b["access_token"], {"goal": "gain"})
    assert patched.status_code == 200

    profile_a = await _load_profile(db_session, uuid.UUID(user_a["user"]["id"]))
    assert profile_a is not None
    assert profile_a.name == "User A Distinguishing"
    assert profile_a.goal == "maintain", "user B's PATCH must never reach user A's row"


async def test_logout_all_never_revokes_user_as_session(client: AsyncClient) -> None:
    user_a = await _register(client)
    user_b = await _register(client)

    response = await _logout_all(client, user_b["access_token"])
    assert response.status_code == 204

    # B's own session is now dead ...
    still_b = await _refresh(client, user_b["refresh_token"])
    assert still_b.status_code == 401
    # ... but A's is untouched.
    still_a = await _refresh(client, user_a["refresh_token"])
    assert still_a.status_code == 200


async def test_delete_account_never_deletes_user_as_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_a = await _register(client)
    user_b = await _register(client)
    user_a_id = uuid.UUID(user_a["user"]["id"])

    response = await _delete_account(client, user_b["access_token"], password=_PASSWORD)
    assert response.status_code == 202

    user_a_row = await _load_user(db_session, user_a_id)
    assert user_a_row.deleted_at is None, "user B's DELETE /account must never delete user A"
    assert user_a_row.is_active is True

    # A's session is still usable -- token_version was never bumped for A.
    still_a = await _refresh(client, user_a["refresh_token"])
    assert still_a.status_code == 200


# --- T-16: GET /exercises, GET /exercises/{id} -- public reference data, no owner ---------
#
# Neither route has a reference field (both are body-less: query params / a path id),
# so neither gets an identifier-substitution case above. What actually needs proving
# for these two is different from the other eight: exercises has no user_id at all
# (§4.10), so there is no "user A's row" to leak -- the caller-specific part is only
# the profile language the name/instructions resolve to (§5.2).

_EXERCISES = "/api/v1/exercises"


async def _list_exercises(client: AsyncClient, access_token: str, **params: str | int) -> Response:
    return await client.get(_EXERCISES, params=params, headers=_auth_headers(access_token))


async def _get_exercise(client: AsyncClient, access_token: str, exercise_id: str) -> Response:
    return await client.get(f"{_EXERCISES}/{exercise_id}", headers=_auth_headers(access_token))


async def test_get_exercises_never_leaks_user_as_language_preference(client: AsyncClient) -> None:
    """exercises has no owner column -- there is no "user A's exercise" for a
    cross-tenant read to leak. What IS caller-specific here is language resolution
    (§5.2): this proves user B's own profile language governs the names they see,
    never user A's, and that both callers reach the identical shared catalogue.
    """
    user_a = await _register(client)
    onboard_a = await _onboard(client, user_a["access_token"], language="en")
    assert onboard_a.status_code == 201

    user_b = await _register(client)
    onboard_b = await _onboard(client, user_b["access_token"], language="ar")
    assert onboard_b.status_code == 201

    response_a = await _list_exercises(client, user_a["access_token"], limit=5)
    response_b = await _list_exercises(client, user_b["access_token"], limit=5)
    assert response_a.status_code == 200
    assert response_b.status_code == 200

    items_a = json_body(response_a)["items"]
    items_b = json_body(response_b)["items"]
    assert [item["id"] for item in items_a] == [item["id"] for item in items_b], (
        "the shared exercise catalogue must not differ by caller"
    )
    # English names are plain ASCII; Arabic names are not -- a cheap, real assertion
    # that the two responses actually resolved to different languages, not a fluke.
    assert all(name.isascii() for name in (item["name"] for item in items_a))
    assert any(not name.isascii() for name in (item["name"] for item in items_b))


async def test_get_exercise_by_id_is_reachable_by_any_onboarded_user(
    client: AsyncClient,
) -> None:
    """A known exercise id must resolve the same way regardless of who asks -- proving
    no accidental per-user scoping bug hides it from (or 404s it for) one caller but
    not another, unlike every owned resource elsewhere in this matrix.
    """
    user_a = await _register(client)
    onboard_a = await _onboard(client, user_a["access_token"])
    assert onboard_a.status_code == 201
    listing = await _list_exercises(client, user_a["access_token"], limit=1)
    exercise_id = json_body(listing)["items"][0]["id"]

    user_b = await _register(client)
    onboard_b = await _onboard(client, user_b["access_token"])
    assert onboard_b.status_code == 201

    response = await _get_exercise(client, user_b["access_token"], exercise_id)
    assert response.status_code == 200
    assert json_body(response)["exercise"]["id"] == exercise_id


# --- T-17: POST /program/generate, GET /program, GET /program/days/{day_id} ---------------

_GENERATE = "/api/v1/program/generate"
_PROGRAM = "/api/v1/program"


async def _generate(client: AsyncClient, access_token: str, days_per_week: int = 4) -> Response:
    return await client.post(
        _GENERATE, json={"days_per_week": days_per_week}, headers=_auth_headers(access_token)
    )


async def _get_program(client: AsyncClient, access_token: str) -> Response:
    return await client.get(_PROGRAM, headers=_auth_headers(access_token))


async def _get_program_day(client: AsyncClient, access_token: str, day_id: str) -> Response:
    return await client.get(f"{_PROGRAM}/days/{day_id}", headers=_auth_headers(access_token))


async def test_generate_program_never_supersedes_user_as_program(client: AsyncClient) -> None:
    """User B generating their own plan must never touch user A's -- proven by A's
    program id staying `is_current` (still returned by GET /program) after B's call,
    the same invariant `ux_one_current_program` (§4.3) would only catch if it were
    scoped globally instead of per-user.
    """
    user_a = await _register(client)
    onboard_a = await _onboard(client, user_a["access_token"])
    assert onboard_a.status_code == 201
    generated_a = await _generate(client, user_a["access_token"], days_per_week=3)
    assert generated_a.status_code == 201
    program_a_id = json_body(generated_a)["program"]["id"]

    user_b = await _register(client)
    onboard_b = await _onboard(client, user_b["access_token"])
    assert onboard_b.status_code == 201
    generated_b = await _generate(client, user_b["access_token"], days_per_week=4)
    assert generated_b.status_code == 201

    still_a = await _get_program(client, user_a["access_token"])
    assert still_a.status_code == 200
    assert json_body(still_a)["program"]["id"] == program_a_id


async def test_get_program_never_returns_user_as_program(client: AsyncClient) -> None:
    user_a = await _register(client)
    onboard_a = await _onboard(client, user_a["access_token"])
    assert onboard_a.status_code == 201
    generated_a = await _generate(client, user_a["access_token"])
    assert generated_a.status_code == 201

    user_b = await _register(client)
    onboard_b = await _onboard(client, user_b["access_token"])
    assert onboard_b.status_code == 201

    # B never generated a plan; the correct 404 is theirs, not a leak of A's program.
    response = await _get_program(client, user_b["access_token"])
    assert response.status_code == 404
    assert response.status_code != 403


async def test_get_program_day_belonging_to_another_user_returns_404(client: AsyncClient) -> None:
    """§6.5 applied to a path parameter this file's body-field scanner cannot see (see
    the comment on this route in `expected_reference_fields` above) -- a program day is
    owned via the parent chain (P2-ADR-09), not directly, so this is the RLS
    parent-EXISTS policy under test, not a hand-written ownership check that could be
    forgotten.
    """
    user_a = await _register(client)
    onboard_a = await _onboard(client, user_a["access_token"])
    assert onboard_a.status_code == 201
    generated_a = await _generate(client, user_a["access_token"])
    assert generated_a.status_code == 201
    day_id = json_body(generated_a)["program"]["days"][0]["id"]

    user_b = await _register(client)
    onboard_b = await _onboard(client, user_b["access_token"])
    assert onboard_b.status_code == 201

    response = await _get_program_day(client, user_b["access_token"], day_id)
    assert response.status_code == 404
    assert response.status_code != 403


# --- T-18: GET /workouts/active -- proven by direct comparison ----------------------------
#
# POST /workouts/{id}/finish and .../abandon take a path `session_id` this file's
# body-field scanner cannot see -- proven directly in
# tests/integration/test_workout_sessions.py instead (the same pattern the comment on
# GET /program/days/{day_id} above documents).

_WORKOUTS = "/api/v1/workouts"
_WORKOUTS_ACTIVE = "/api/v1/workouts/active"


async def _get_active_workout(client: AsyncClient, access_token: str) -> Response:
    return await client.get(_WORKOUTS_ACTIVE, headers=_auth_headers(access_token))


async def test_get_active_workout_never_returns_user_as_session(client: AsyncClient) -> None:
    user_a = await _register(client)
    onboard_a = await _onboard(client, user_a["access_token"])
    assert onboard_a.status_code == 201
    started_a = await client.post(_WORKOUTS, json={}, headers=_auth_headers(user_a["access_token"]))
    assert started_a.status_code == 201

    user_b = await _register(client)
    onboard_b = await _onboard(client, user_b["access_token"])
    assert onboard_b.status_code == 201

    # B has no session of their own -- the correct 204 is theirs, not a leak of A's.
    response = await _get_active_workout(client, user_b["access_token"])
    assert response.status_code == 204
    assert response.status_code != 403
