"""A.5 item 15: `app.integrations.firebase` used to initialise the Firebase Admin SDK at
import time, so importing `app.main` -- uvicorn, `scripts/export_openapi.py`, any CLI --
required a valid `FIREBASE_CREDENTIALS_JSON` even when nothing social was ever going to be
called. Init moved into main.py's lifespan handler, beside the privilege assertion; these
tests are the control that it actually stopped mattering at import time and start being
enforced only where it should be: when a social route is actually used.

Driven through the real FastAPI lifespan (`app.router.lifespan_context`), same pattern as
`test_startup_privilege_check.py`, not by calling `firebase.init_firebase()` directly --
the httpx `client` fixture's ASGITransport never runs lifespan events, so a regression
that quietly re-added import-time init elsewhere would not be caught by calling the helper
in isolation.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core.rate_limit import limiter
from app.integrations import firebase
from app.main import create_app

# No module-level `pytestmark = pytest.mark.asyncio`: pyproject.toml sets
# `asyncio_mode = "auto"`, and this file (unlike test_social_auth.py's) also has a plain
# sync test below -- an explicit mark on a non-async test is a pytest-asyncio warning.


@pytest.fixture(autouse=True)
def _isolated_rate_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


async def test_app_starts_when_firebase_credentials_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control for A.5 item 15: no social route has been called, so a missing
    service-account JSON must not stop the app from starting at all."""
    monkeypatch.setattr(settings, "FIREBASE_CREDENTIALS_JSON", None)
    app = create_app()

    async with app.router.lifespan_context(app):
        pass  # must not raise

    assert firebase._app is None


async def test_social_route_without_credentials_fails_cleanly_not_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the control: once a social route IS called without Firebase
    configured, the request must fail with a structured error response, not a raw 500
    or an unhandled exception surfacing before the app ever starts serving traffic.

    A.5 item 16: a missing/malformed FIREBASE_CREDENTIALS_JSON is exactly the
    deployment-misconfiguration case that endpoint now reports as
    503 UPSTREAM_UNAVAILABLE rather than 401 SOCIAL_TOKEN_INVALID -- see
    test_social_auth.py's item-16 tests for the code-level assertion on that mapping.
    This test's own concern is narrower and unchanged by that: whatever the code is,
    it must be a structured problem+json response, not an unhandled 500.
    """
    monkeypatch.setattr(settings, "FIREBASE_CREDENTIALS_JSON", None)
    app = create_app()
    transport = ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/auth/social/google", json={"id_token": "whatever-not-checked"}
            )

    body = response.json()
    assert response.status_code == 503, body
    assert body["code"] == "UPSTREAM_UNAVAILABLE", body


async def test_verify_id_token_raises_cleanly_when_not_initialised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit-level control on `firebase.py` itself: calling the SDK wrapper with no app
    initialised is a clean, typed failure (RuntimeError), not an AttributeError from
    passing `app=None` down into firebase_admin."""
    monkeypatch.setattr(firebase, "_app", None)

    with pytest.raises(RuntimeError, match="not initialised"):
        firebase.verify_id_token("whatever-not-checked")


def test_init_firebase_is_idempotent_across_repeated_calls() -> None:
    """firebase_admin keeps a process-global registry of apps keyed by name, and this
    suite's own `client` fixture calls `create_app()` (and, elsewhere, the lifespan
    itself) more than once per process -- as would a `uvicorn --reload` cycle in dev. A
    naive second `initialize_app()` raises "The default Firebase app already exists.";
    this is the control that `init_firebase()`'s delete-then-recreate guard prevents it."""
    firebase.init_firebase()
    first_app = firebase._app
    assert first_app is not None

    firebase.init_firebase()  # must not raise
    second_app = firebase._app
    assert second_app is not None
    assert second_app is not first_app
