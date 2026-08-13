"""Response shapes for spec §5.2 (GET /exercises, GET /exercises/{id}, P2-FR-001).

Following schemas/auth.py and schemas/profile.py's convention: nothing here parses a
request body (both routes take query/path parameters, read directly in the router), so
there is no pydantic validator that could raise and produce FastAPI's default error
body instead of the §7.2 envelope.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

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
