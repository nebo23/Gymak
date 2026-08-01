"""Firebase Admin SDK wiring (P1-ADR-01, §8.3, §12 T-06, A.5 item 15).

Firebase is used for exactly one job here: verifying that a Google sign-in really
happened. `verify_id_token` is the only function this module exposes to callers, and
app/services/social_service.py is its only caller -- nothing else in this codebase
imports firebase_admin directly (P1-ADR-01: "Firestore, Firebase Realtime Database, and
Firebase-managed email/password accounts are not used").

`init_firebase()` used to run at import time -- the same shape as the `database.py`
defect T-04b fixed (Appendix A.5 item 10), minus the event-loop crash. Importing this
module transitively imports `app.main` (via social_service -> routers.auth), so anything
that merely imports the app -- uvicorn, `scripts/export_openapi.py`, any CLI, any test
that never touches social sign-in -- required a valid service-account JSON just to start.
It is now called explicitly from main.py's lifespan handler, beside the privilege
assertion, so the app can start without Firebase configured; social sign-in alone is
unavailable until it is.
"""

from __future__ import annotations

import json
from typing import Any, cast

import firebase_admin
from firebase_admin import auth, credentials

from app.config import settings

_app: firebase_admin.App | None = None


def init_firebase() -> None:
    """Called once from app.main's lifespan handler, not at import time.

    A no-op (leaves `_app` as `None`) when `FIREBASE_CREDENTIALS_JSON` is not set --
    `verify_id_token` below then fails cleanly instead of ever reaching the SDK. When it
    is set, this still fails at startup, not at the first sign-in, for a malformed
    credential -- `credentials.Certificate` validates the required fields locally.

    Idempotent: deletes any existing default app first, so calling this more than once in
    the same process (a second `create_app()` in the test suite, an app reload) does not
    hit firebase_admin's "default app already exists" error.
    """
    global _app
    if settings.FIREBASE_CREDENTIALS_JSON is None:
        _app = None
        return

    try:
        existing_app = firebase_admin.get_app()
    except ValueError:
        existing_app = None
    if existing_app is not None:
        firebase_admin.delete_app(existing_app)

    credential = credentials.Certificate(json.loads(settings.FIREBASE_CREDENTIALS_JSON))
    _app = firebase_admin.initialize_app(credential)


def verify_id_token(id_token: str) -> dict[str, Any]:
    """§5.4 step 1: verify with the admin SDK, never decode manually. `check_revoked=True`
    per spec.

    Raises RuntimeError, cleanly, if `init_firebase()` was never called or ran with no
    credentials configured -- rather than an AttributeError from a None app reaching the
    SDK. social_service wraps every failure from this function into
    401 SOCIAL_TOKEN_INVALID (it does not distinguish "not configured" from "bad token"),
    so either way the caller gets a proper problem+json response, not a 500.

    Otherwise raises whatever firebase_admin.auth raises on any failure (invalid
    signature, expired, revoked, wrong project, ...) -- every one of those is a
    firebase_admin.exceptions.FirebaseError.
    """
    if _app is None:
        raise RuntimeError(
            "Firebase Admin SDK is not initialised: FIREBASE_CREDENTIALS_JSON is not "
            "set. Social sign-in is unavailable until it is configured."
        )
    return cast(dict[str, Any], auth.verify_id_token(id_token, app=_app, check_revoked=True))
