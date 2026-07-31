"""Business logic for §5.8 (POST /profile) and §5.9 (PATCH /profile), plus P1-SAF-001.
No HTTP objects here (§3) -- the router passes plain values (a validated request
schema, the authenticated User) and gets a plain model or tuple back.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    GoalNotPermittedForMinorError,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    ValidationError,
)
from app.models.profile import Profile
from app.models.user import User
from app.repositories import audit_repo, profile_repo
from app.schemas.profile import ProfileCreateRequest, ProfileUpdateRequest

# =========================================================================================
# P1-SAF-001 -- a user under 18 cannot select the 'lose' goal. Pure functions, no I/O, so
# they are unit-testable at their boundaries without a database (tests/unit/test_saf_age_goal.py).
# =========================================================================================

ADULT_AGE = 18
RESTRICTED_GOAL = "lose"
PERMITTED_GOALS_FOR_MINOR = ("maintain", "gain")


def compute_age(birth_date: date, *, today: date | None = None) -> int:
    """§4.3: "age is computed from birth_date, never stored." `today` is a parameter,
    not `date.today()` read internally, so the boundary tests (17y 364d, exactly 18,
    18y 1d) can pin the "now" side of the calculation instead of racing a real clock.
    """
    as_of = today if today is not None else date.today()
    years = as_of.year - birth_date.year
    if (as_of.month, as_of.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def assert_goal_permitted(birth_date: date, goal: str, *, today: date | None = None) -> None:
    """§5.8/§5.9: "if the age implied by birth_date is under 18 and goal == 'lose',
    reject with 422 GOAL_NOT_PERMITTED_FOR_MINOR and a detail naming maintain and gain
    as the permitted values." Called on every POST and every PATCH, re-evaluated
    against whatever birth_date/goal will be in force after the request applies.
    """
    if goal == RESTRICTED_GOAL and compute_age(birth_date, today=today) < ADULT_AGE:
        raise GoalNotPermittedForMinorError(
            detail=f"Permitted goals for this account: {', '.join(PERMITTED_GOALS_FOR_MINOR)}."
        )


# =========================================================================================
# §7.1 field validation. Each raises app.core.errors.ValidationError with the field code
# the client switches on, mirroring auth_service's validate_password / validate_email_format.
# =========================================================================================

_GENDERS = {"male", "female"}
_GOALS = {"lose", "gain", "maintain"}
_EXPERIENCE_LEVELS = {"beginner", "intermediate", "advanced"}
_ACTIVITY_LEVELS = {"sedentary", "light", "moderate", "high", "very_high"}
_UNIT_SYSTEMS = {"metric", "imperial"}
_LANGUAGES = {"ar", "en"}

_MIN_AGE = 13
_MAX_AGE = 100
_MIN_HEIGHT_CM = Decimal("100")
_MAX_HEIGHT_CM = Decimal("250")
_MIN_WEIGHT_KG = Decimal("30")
_MAX_WEIGHT_KG = Decimal("300")


def _field_error(field: str, code: str, detail: str) -> ValidationError:
    return ValidationError(detail=detail, errors=[{"field": field, "code": code}])


def validate_name(raw: str) -> str:
    """§7.1: "2-60 chars after trimming; Arabic and Latin letters, spaces, hyphens,
    apostrophes; no digits, no emoji." §4.3: "trimmed, collapsed whitespace." `str.isalpha()`
    is Unicode-aware -- true for Arabic and Latin letters, false for digits, emoji and
    other punctuation -- so it is the whole character-class check in one call.
    """
    name = " ".join(raw.split())
    if not (2 <= len(name) <= 60) or not all(ch.isalpha() or ch in " '-" for ch in name):
        raise _field_error("name", "INVALID", "Enter a valid name.")
    return name


def validate_gender(value: str) -> str:
    if value not in _GENDERS:
        raise _field_error("gender", "NOT_ALLOWED", "gender must be 'male' or 'female'.")
    return value


def validate_birth_date(raw: str) -> date:
    """§7.1: "ISO date, age between 13 and 100, not in the future." A malformed string
    and an out-of-range date both surface as birth_date:OUT_OF_RANGE -- the spec defines
    no separate code for a parse failure, and either way the date offered is not usable.
    """
    try:
        parsed = date.fromisoformat(raw)
    except (ValueError, TypeError) as exc:
        raise _field_error(
            "birth_date", "OUT_OF_RANGE", "Enter a valid birth date (YYYY-MM-DD)."
        ) from exc

    today = date.today()
    if parsed > today or not (_MIN_AGE <= compute_age(parsed, today=today) <= _MAX_AGE):
        raise _field_error("birth_date", "OUT_OF_RANGE", "Age must be between 13 and 100 years.")
    return parsed


def validate_height_cm(value: Decimal) -> Decimal:
    if not (_MIN_HEIGHT_CM <= value <= _MAX_HEIGHT_CM):
        raise _field_error("height_cm", "OUT_OF_RANGE", "height_cm must be between 100 and 250.")
    return value


def validate_weight_kg(value: Decimal) -> Decimal:
    if not (_MIN_WEIGHT_KG <= value <= _MAX_WEIGHT_KG):
        raise _field_error("weight_kg", "OUT_OF_RANGE", "weight_kg must be between 30 and 300.")
    return value


def validate_goal(value: str) -> str:
    if value not in _GOALS:
        raise _field_error("goal", "NOT_ALLOWED", "goal must be 'lose', 'gain' or 'maintain'.")
    return value


def validate_experience_level(value: str) -> str:
    if value not in _EXPERIENCE_LEVELS:
        raise _field_error(
            "experience_level",
            "NOT_ALLOWED",
            "experience_level must be 'beginner', 'intermediate' or 'advanced'.",
        )
    return value


def validate_activity_level(value: str) -> str:
    if value not in _ACTIVITY_LEVELS:
        raise _field_error(
            "activity_level", "NOT_ALLOWED", "activity_level is not one of the allowed values."
        )
    return value


def validate_unit_system(value: str) -> str:
    if value not in _UNIT_SYSTEMS:
        raise _field_error(
            "unit_system", "NOT_ALLOWED", "unit_system must be 'metric' or 'imperial'."
        )
    return value


def validate_language(value: str) -> str:
    if value not in _LANGUAGES:
        raise _field_error("language", "NOT_ALLOWED", "language must be 'ar' or 'en'.")
    return value


# =========================================================================================
# §5.8 POST /profile
# =========================================================================================


async def create_profile(
    session: AsyncSession, user: User, body: ProfileCreateRequest
) -> tuple[Profile, int]:
    """§5.8: validate every field, enforce P1-SAF-001, then insert -- once. Returns the
    new row plus the derived age the response body carries (never stored, §4.3).

    Field validation runs before the existence check, matching auth_service.register's
    own ordering (validate, then check the 409 conflict) rather than the reverse.
    """
    name = validate_name(body.name)
    gender = validate_gender(body.gender)
    birth_date = validate_birth_date(body.birth_date)
    height_cm = validate_height_cm(body.height_cm)
    weight_kg = validate_weight_kg(body.weight_kg) if body.weight_kg is not None else None
    goal = validate_goal(body.goal)
    experience_level = validate_experience_level(body.experience_level)
    activity_level = (
        validate_activity_level(body.activity_level) if body.activity_level is not None else None
    )
    unit_system = validate_unit_system(body.unit_system)
    language = validate_language(body.language)

    assert_goal_permitted(birth_date, goal)

    # §5.8: "enforced by the primary key rather than by application politeness." The
    # pre-check below gives a clean 409 on the common case; the try/except is what
    # actually guarantees it under a concurrent double-POST, where two requests can both
    # pass the pre-check before either has inserted (verified against the profiles.user_id
    # PK, not merely assumed).
    if await profile_repo.get_by_user_id(session, user.id) is not None:
        raise ProfileAlreadyExistsError(
            detail="Onboarding has already been completed for this account."
        )

    try:
        profile = await profile_repo.create_profile(
            session,
            user.id,
            name=name,
            gender=gender,
            birth_date=birth_date,
            height_cm=height_cm,
            weight_kg=weight_kg,
            goal=goal,
            experience_level=experience_level,
            activity_level=activity_level,
            unit_system=unit_system,
            language=language,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise ProfileAlreadyExistsError(
            detail="Onboarding has already been completed for this account."
        ) from exc

    await audit_repo.record(
        session,
        action="profile.created",
        actor_user_id=user.id,
        entity="profile",
        entity_id=user.id,
    )
    await session.commit()
    return profile, compute_age(birth_date)


# =========================================================================================
# §5.9 GET / PATCH /profile
# =========================================================================================


async def get_profile(session: AsyncSession, user: User) -> Profile:
    profile = await profile_repo.get_by_user_id(session, user.id)
    if profile is None:
        raise ProfileNotFoundError(detail="No profile exists for this account yet.")
    return profile


async def update_profile(session: AsyncSession, user: User, body: ProfileUpdateRequest) -> Profile:
    """§5.9's editable/immutable table. `onboarding_completed` is excluded up front --
    "A client sending it is ignored, not rejected" -- so it can never appear in `changes`
    even though the schema accepts it. gender/birth_date changes are audited with their
    before and after value; the rest are not (the table marks only those two "audited").
    """
    profile = await get_profile(session, user)

    changes = body.model_dump(exclude_unset=True, exclude={"onboarding_completed"})
    if not changes:
        raise ValidationError(detail="The request body must include at least one field to update.")

    updates: dict[str, Any] = {}
    audit_metadata: dict[str, Any] = {}

    if "name" in changes:
        updates["name"] = validate_name(changes["name"])
    if "gender" in changes:
        new_gender = validate_gender(changes["gender"])
        if new_gender != profile.gender:
            audit_metadata["gender"] = {"before": profile.gender, "after": new_gender}
        updates["gender"] = new_gender
    if "birth_date" in changes:
        new_birth_date = validate_birth_date(changes["birth_date"])
        if new_birth_date != profile.birth_date:
            audit_metadata["birth_date"] = {
                "before": profile.birth_date.isoformat(),
                "after": new_birth_date.isoformat(),
            }
        updates["birth_date"] = new_birth_date
    if "height_cm" in changes:
        updates["height_cm"] = validate_height_cm(changes["height_cm"])
    if "weight_kg" in changes:
        weight_kg = changes["weight_kg"]
        updates["weight_kg"] = validate_weight_kg(weight_kg) if weight_kg is not None else None
    if "goal" in changes:
        updates["goal"] = validate_goal(changes["goal"])
    if "experience_level" in changes:
        updates["experience_level"] = validate_experience_level(changes["experience_level"])
    if "activity_level" in changes:
        activity_level = changes["activity_level"]
        updates["activity_level"] = (
            validate_activity_level(activity_level) if activity_level is not None else None
        )
    if "unit_system" in changes:
        updates["unit_system"] = validate_unit_system(changes["unit_system"])
    if "language" in changes:
        updates["language"] = validate_language(changes["language"])

    # Re-checked on every PATCH (§5.8/§5.9), against the state that will result once
    # this update applies -- not just when birth_date or goal is the field that changed.
    resulting_birth_date = updates.get("birth_date", profile.birth_date)
    resulting_goal = updates.get("goal", profile.goal)
    assert_goal_permitted(resulting_birth_date, resulting_goal)

    updated = await profile_repo.update_profile(session, user.id, **updates)

    if audit_metadata:
        await audit_repo.record(
            session,
            action="profile.updated",
            actor_user_id=user.id,
            entity="profile",
            entity_id=user.id,
            metadata=audit_metadata,
        )

    await session.commit()
    return updated
