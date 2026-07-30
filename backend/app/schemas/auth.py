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
