"""Shapes for spec §5.2 (GET /exercises, GET /exercises/{id}, P2-FR-001) and for the
owner-authorised custom-exercise routes (POST/PATCH/DELETE /exercises).

The read models follow schemas/auth.py and schemas/profile.py's convention. The two
request models below DO parse a body, and deliberately carry no pydantic validator that
can raise: every closed-vocabulary check is done in the router against the tuples
exported by models/exercise.py, so a bad value produces the §7.2 envelope with a
per-field code rather than FastAPI's own 422 body. The only constraints expressed here
are pydantic's own length/shape ones on free text, which produce a body the router's
RequestValidationError handler already converts.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.exercise import Exercise


class ExerciseListItem(BaseModel):
    """§5.2: `name` is resolved server-side from the caller's profile language -- the
    one deliberate exception to "the server never sends display text" (Phase 1 §9.6),
    made because shipping both languages' names to every client for a ~60-row library
    doubles the payload for no client that ever shows both at once.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    primary_muscle: str
    secondary_muscles: list[str]
    equipment: str
    movement_pattern: str
    is_compound: bool
    difficulty: str
    # Derived from `user_id`, never the id itself: the client needs to know "this is
    # mine" (to badge it, and to show edit/delete) but has no use for the owner uuid,
    # and shipping an owner id to the client would be the only place in the API that
    # names a user other than through the bearer token.
    is_custom: bool


class ExerciseDetail(ExerciseListItem):
    """§5.2: "GET /exercises/{id} additionally returns instructions." """

    instructions: str


class ExerciseListResponse(BaseModel):
    items: list[ExerciseListItem]
    next_cursor: str | None


class ExerciseDetailResponse(BaseModel):
    exercise: ExerciseDetail


def _resolved_name(exercise: Exercise, language: str) -> str:
    return exercise.name_ar if language == "ar" else exercise.name_en


def build_list_item(exercise: Exercise, *, language: str) -> ExerciseListItem:
    return ExerciseListItem(
        id=exercise.id,
        slug=exercise.slug,
        name=_resolved_name(exercise, language),
        is_custom=exercise.user_id is not None,
        primary_muscle=exercise.primary_muscle,
        secondary_muscles=list(exercise.secondary_muscles),
        equipment=exercise.equipment,
        movement_pattern=exercise.movement_pattern,
        is_compound=exercise.is_compound,
        difficulty=exercise.difficulty,
    )


def build_detail(exercise: Exercise, *, language: str) -> ExerciseDetail:
    instructions = exercise.instructions_ar if language == "ar" else exercise.instructions_en
    return ExerciseDetail(
        **build_list_item(exercise, language=language).model_dump(),
        instructions=instructions,
    )


# §5.2's list/detail models above are responses. Everything below is a request body for
# the custom-exercise routes.

_NAME_MAX = 80
_INSTRUCTIONS_MAX = 2000
_SECONDARY_MUSCLES_MAX = 5


class ExerciseCreateRequest(BaseModel):
    """POST /exercises. One `name`, in whichever language the user typed -- see
    `exercise_repo.create_custom` for why it is written to both name columns rather than
    translated or left blank.

    Every closed-vocabulary field is a bare `str` here and validated in the router
    against models/exercise.py's exported tuples, the same tuples the CHECK constraints
    are built from. Typing them as Literal/Enum would move the failure into pydantic and
    produce FastAPI's 422 body instead of §7.2's envelope with a per-field code.
    """

    name: str = Field(min_length=1, max_length=_NAME_MAX)
    primary_muscle: str
    equipment: str
    movement_pattern: str
    difficulty: str
    is_compound: bool = False
    secondary_muscles: list[str] = Field(default_factory=list, max_length=_SECONDARY_MUSCLES_MAX)
    instructions: str = Field(default="", max_length=_INSTRUCTIONS_MAX)


class ExerciseUpdateRequest(BaseModel):
    """PATCH /exercises/{id}. Every field optional; only what is sent is changed. `None`
    means "not sent" rather than "clear it" -- none of these columns is nullable, so
    there is nothing a client could legitimately clear.
    """

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    primary_muscle: str | None = None
    equipment: str | None = None
    movement_pattern: str | None = None
    difficulty: str | None = None
    is_compound: bool | None = None
    secondary_muscles: list[str] | None = Field(default=None, max_length=_SECONDARY_MUSCLES_MAX)
    instructions: str | None = Field(default=None, max_length=_INSTRUCTIONS_MAX)


class ExerciseDeleteResponse(BaseModel):
    """§5.2's soft delete: the row stays resolvable by id for sessions that logged it,
    so the response reports what actually happened rather than an empty 204 that would
    imply the row is gone.
    """

    id: uuid.UUID
    is_active: bool
