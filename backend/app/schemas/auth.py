"""Request/response shapes for spec §5.2 (register) and §5.3 (login).

Fields are deliberately plain `str` with no pydantic validator that raises. A validator
that raises turns into pydantic's own ValidationError, which FastAPI converts to a
RequestValidationError and answers with FastAPI's default body -- not the §7.2
problem+json envelope. Content validation (email shape, password policy) therefore
happens explicitly in auth_service, which raises app.core.errors.ValidationError itself
and gets the correct envelope for free through the AppError handler already registered
in core/errors.py.
"""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, ConfigDict

from app.core.errors import ValidationError

# §7.1: "RFC-shaped, <=254 chars ... MX not checked." A pragmatic shape check, not a full
# RFC 5322 grammar -- MX is explicitly out of scope and a hand-rolled full-grammar regex
# would reject as many valid addresses as invalid ones. No `email-validator` dependency:
# it is not in Appendix A.2, and A.2 permits nothing else without asking first.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EMAIL_MAX_LENGTH = 254


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    language: str = "ar"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class RefreshRequest(BaseModel):
    """§5.5. The opaque refresh token is the only field -- there is no bearer here."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class LogoutRequest(BaseModel):
    """§5's /auth/logout. The access token identifies the caller; it carries no
    family_id (P1-ADR-02's claim list), so the refresh token is what tells the server
    which family to revoke.
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    """§5.6 call 1. `email` is the only field -- deliberately unauthenticated."""

    model_config = ConfigDict(extra="forbid")

    email: str


class ForgotPasswordResponse(BaseModel):
    """§5.6: the exact same body regardless of whether the account exists."""

    message: str = "If an account exists for that address, a code has been sent."


class VerifyCodeRequest(BaseModel):
    """§5.6 call 2. `code` is validated by attempting a match, not by a schema-level
    shape check -- see password_reset_service: a malformed code cannot match any
    stored digest, so it already surfaces as RESET_CODE_INVALID (§7.1) through the
    same path a wrong-but-well-formed code takes, with no separate rule to keep in
    sync with P1-ADR-07's alphabet.
    """

    model_config = ConfigDict(extra="forbid")

    email: str
    code: str


class VerifyCodeResponse(BaseModel):
    """§5.6: opaque, single-purpose, single-use, 5 minutes."""

    reset_token: str
    expires_in: int


class ResetPasswordRequest(BaseModel):
    """§5.6 call 3. No email here -- the reset token alone identifies the account."""

    model_config = ConfigDict(extra="forbid")

    reset_token: str
    new_password: str


class SocialSignInRequest(BaseModel):
    """§5.4. "The body carries exactly one field: id_token." Deliberately NOT
    extra="forbid" like this module's other request schemas: §5.4's own security note --
    "the provider, the uid, and the email all come from the verified token -- never from
    the request body" -- means an attacker-supplied `email` or `provider` alongside a
    valid id_token must be silently ignored, not rejected as an unknown field. See
    test_social_auth.py's body-field-ignored control test.
    """

    model_config = ConfigDict(extra="ignore")

    id_token: str


class UserSummary(BaseModel):
    id: uuid.UUID
    email: str
    onboarding_completed: bool


class TokenPairResponse(BaseModel):
    """Identical shape for register (§5.2) and login (§5.3)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: UserSummary


class SocialSignInResponse(TokenPairResponse):
    """§5.4: identical shape to register/login's token pair, plus is_new_user so the
    client knows whether to route to onboarding or home.
    """

    is_new_user: bool


def normalise_email(raw: str) -> str:
    """§5 convention: "Email addresses are lowercased and trimmed before any lookup or
    insert." Centralised here so register and login normalise identically instead of
    each reimplementing it.
    """
    return raw.strip().lower()


def validate_email_format(email: str) -> None:
    """§7.1's email rule, raised as the app's own ValidationError (422) rather than a
    pydantic field validator -- see the module docstring for why. Call this on an
    already-normalised (normalise_email) address.
    """
    if not email or len(email) > _EMAIL_MAX_LENGTH or not _EMAIL_RE.match(email):
        raise ValidationError(
            detail="Enter a valid email address.",
            errors=[{"field": "email", "code": "INVALID"}],
        )
