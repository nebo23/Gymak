"""Firebase Admin SDK wiring (P1-ADR-01, §8.3, §12 T-06).

Firebase is used for exactly one job here: verifying that a Google sign-in really
happened. `verify_id_token` is the only function this module exposes, and
app/services/social_service.py is its only caller -- nothing else in this codebase
imports firebase_admin directly (P1-ADR-01: "Firestore, Firebase Realtime Database, and
Firebase-managed email/password accounts are not used").
"""

from __future__ import annotations

import json
from typing import Any, cast

import firebase_admin
from firebase_admin import auth, credentials

from app.config import settings

# Initialised once, at import, from FIREBASE_CREDENTIALS_JSON (§8.3) -- the same
# "fail fast at import" posture config.py already takes with JWT_PRIVATE_KEY_PEM and
# RESET_CODE_PEPPER: a malformed service-account JSON should stop the process at
# startup, not surface as an opaque error on the first sign-in attempt.
_credentials = credentials.Certificate(json.loads(settings.FIREBASE_CREDENTIALS_JSON))
_app = firebase_admin.initialize_app(_credentials)


def verify_id_token(id_token: str) -> dict[str, Any]:
    """§5.4 step 1: verify with the admin SDK, never decode manually. `check_revoked=True`
    per spec.

    Raises whatever firebase_admin.auth raises on any failure (invalid signature,
    expired, revoked, wrong project, ...) -- every one of those is a
    firebase_admin.exceptions.FirebaseError. social_service maps all of them to
    401 SOCIAL_TOKEN_INVALID without distinguishing which; that mapping lives there, not
    here, so this module stays a thin, honest wrapper over the SDK call.
    """
    return cast(dict[str, Any], auth.verify_id_token(id_token, app=_app, check_revoked=True))
