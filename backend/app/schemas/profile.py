"""Request/response shapes for spec §5.7 (the profile half), §5.8 (POST /profile) and
§5.9 (PATCH /profile).

Following schemas/auth.py's convention: fields are plain, permissive types with no
pydantic validator that raises. A raising validator becomes pydantic's own
ValidationError, which FastAPI turns into its own default error body -- not the §7.2
problem+json envelope. Content validation (ranges, enums, the name character set,
P1-SAF-001) happens explicitly in profile_service, which raises
app.core.errors.ValidationError / GoalNotPermittedForMinorError itself and gets the
correct envelope for free through the AppError handler already registered in
core/errors.py.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

# height_cm/weight_kg are stored as Numeric(5,1)/Numeric(5,2) (unchanged) and parsed
# into Decimal as before; this only changes how ProfileData renders them on the wire.
# Pydantic v2 serializes bare Decimal fields to JSON strings by default, but §5.8's
# example gives them as JSON numbers -- when_used="json" leaves python-mode
# model_dump() (Decimal) untouched and only casts to float for JSON output.
DecimalAsFloat = Annotated[
    Decimal, PlainSerializer(lambda value: float(value), return_type=float, when_used="json")
]


class ProfileCreateRequest(BaseModel):
    """§5.8. birth_date is a plain str (not a pydantic `date`), deliberately -- see the
    module docstring: a malformed date string must reach profile_service as a
    VALIDATION_ERROR, not FastAPI's default body.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    gender: str
    birth_date: str
    height_cm: Decimal
    weight_kg: Decimal | None = None
    goal: str
    experience_level: str
    activity_level: str | None = None
    unit_system: str = "metric"
    language: str = "ar"


class ProfileUpdateRequest(BaseModel):
    """§5.9's editable/immutable table. Every field is optional so `model_dump(
    exclude_unset=True)` in profile_service tells "not sent" from "sent", which is what
    "only the keys present in the body are touched" (partial update) requires.

    `onboarding_completed` is declared explicitly, and only so `extra="forbid"` does not
    reject it -- §5.9: "Server-controlled. A client sending it is ignored, not
    rejected." profile_service never reads this field.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    gender: str | None = None
    birth_date: str | None = None
    height_cm: Decimal | None = None
    weight_kg: Decimal | None = None
    goal: str | None = None
    experience_level: str | None = None
    activity_level: str | None = None
    unit_system: str | None = None
    language: str | None = None
    onboarding_completed: bool | None = None


class ProfileData(BaseModel):
    """The full profile object shape shared by /auth/me, and the POST/GET/PATCH
    /profile responses (§5.7, §5.8, §5.9)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    gender: str
    birth_date: date
    height_cm: DecimalAsFloat
    weight_kg: DecimalAsFloat | None
    goal: str
    experience_level: str
    activity_level: str | None
    unit_system: str
    language: str
    onboarding_completed: bool
    created_at: datetime
    updated_at: datetime


class DerivedFields(BaseModel):
    """§5.8: "age is computed, never stored." """

    age: int


class ProfileCreateResponse(BaseModel):
    profile: ProfileData
    derived: DerivedFields


class ProfileResponse(BaseModel):
    profile: ProfileData
