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
    """Canary for `_enumerate_api_routes` itself: spec §5.1's endpoint catalogue has
    exactly 15 rows (14 API endpoints plus /health). If a future FastAPI version changes
    how `include_router` wires routes again, this fails immediately instead of the
    matrix below silently running zero cases.
    """
    routes = _enumerate_api_routes()
    found = sorted(_route_key(r) for r in routes)
    assert len(routes) == 15, f"expected 15 routes per spec §5.1, found {len(routes)}: {found}"


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

    # Of 15 enumerated routes, 8 are unauthenticated by design (register, login, social
    # sign-in, refresh, the three password-reset calls, and health) and are scoped, if
    # at all, by a submitted email/token under their own §7.3 error contract rather than
    # by a bearer identity -- not this matrix's concern. The remaining 7 are user-scoped;
    # of those, 6 accept no field that could name another user's resource at all (the
    # only "identifier" is the bearer token itself), and are instead each proven
    # isolated by their own test below; 1 (POST /auth/logout's refresh_token) does name
    # another row and is the one live identifier-substitution case.
    assert len(routes) == 15
    assert len(user_scoped) == 7


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


def _identifier_value_for(field: str, *, other_refresh_token: str) -> str:
    """The real value belonging to "the other user" for a given reference field.

    Deliberately a lookup, not a generic fabrication: a future reference field this
    file has not been taught to source raises KeyError, which fails its parametrized
    case loudly rather than silently passing an untested substitution.
    """
    known = {"refresh_token": other_refresh_token}
    return known[field]


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

    identifier = _identifier_value_for(field, other_refresh_token=user_a["refresh_token"])
    body = {field: identifier} if field != "refresh_token" else {"refresh_token": identifier}

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
