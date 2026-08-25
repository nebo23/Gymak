from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.database import Base

# spec §4.1a -- the closed muscle vocabulary. Seventeen values; adding an eighteenth is a
# migration plus a translation key plus a generator review, not a casual change.
_MUSCLES = (
    "chest",
    "back",
    "lats",
    "traps",
    "front_delts",
    "side_delts",
    "rear_delts",
    "biceps",
    "triceps",
    "forearms",
    "quads",
    "hamstrings",
    "glutes",
    "calves",
    "abs",
    "obliques",
    "lower_back",
)
_EQUIPMENT = ("barbell", "dumbbell", "machine", "cable", "bodyweight", "kettlebell", "band")
_MOVEMENT_PATTERNS = (
    "squat",
    "hinge",
    "horizontal_push",
    "vertical_push",
    "horizontal_pull",
    "vertical_pull",
    "lunge",
    "carry",
    "isolation",
)
_DIFFICULTIES = ("beginner", "intermediate", "advanced")


class Exercise(Base):
    """spec §4.1, P2-ADR-02, plus the owner-authorised departure from §1.2 that added
    user-owned custom rows (migration a1c9f2e4b703).

    Two kinds of row live here now. `user_id IS NULL` is a seeded, public row: owned by
    a migration, identical in every environment (the seed file carries a fixed UUID v7
    per row, which is why `id` has no Python-side default), and still writable by nobody
    through the app role. `user_id` set is one user's own exercise, created through
    POST /exercises so it can be logged against when the library lacks a movement.

    RLS backs that split rather than convention: a SELECT policy admitting
    `user_id IS NULL OR user_id = <app user>`, and INSERT/UPDATE policies admitting only
    the caller's own rows, so a seeded row can be neither forged nor edited. DELETE is
    not granted to the app role at all -- retiring a custom row is `is_active = false`,
    the same soft delete P2-ADR-02 built for seeded rows, which is also all that
    `workout_sets.exercise_id`'s ON DELETE RESTRICT would permit.
    """

    __tablename__ = "exercises"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_exercises_slug"),
        CheckConstraint(
            "primary_muscle IN ({})".format(", ".join(f"'{m}'" for m in _MUSCLES)),
            name="chk_exercises_primary_muscle",
        ),
        CheckConstraint(
            "equipment IN ({})".format(", ".join(f"'{e}'" for e in _EQUIPMENT)),
            name="chk_exercises_equipment",
        ),
        CheckConstraint(
            "movement_pattern IN ({})".format(", ".join(f"'{p}'" for p in _MOVEMENT_PATTERNS)),
            name="chk_exercises_movement_pattern",
        ),
        CheckConstraint(
            "difficulty IN ({})".format(", ".join(f"'{d}'" for d in _DIFFICULTIES)),
            name="chk_exercises_difficulty",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    # NULL = seeded/public; set = that user's own row. ON DELETE CASCADE so a purged
    # user takes their own exercises with them (see the migration's note on how that
    # meets workout_sets' ON DELETE RESTRICT).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # Globally unique even for custom rows: `exercise_repo.build_custom_slug` prefixes
    # them per user, which is what lets uq_exercises_slug stay a single-column
    # constraint and list_active keep paginating by keyset on slug alone.
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    primary_muscle: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_muscles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    equipment: Mapped[str] = mapped_column(Text, nullable=False)
    movement_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    is_compound: Mapped[bool] = mapped_column(Boolean, nullable=False)
    difficulty: Mapped[str] = mapped_column(Text, nullable=False)
    instructions_en: Mapped[str] = mapped_column(Text, nullable=False)
    instructions_ar: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Public aliases for the four closed vocabularies above. POST/PATCH /exercises validates
# against exactly these, so a custom row can never carry a value the CHECK constraints
# they are built from would reject -- one source of truth rather than a second copy in
# the schema layer that could drift from the database.
MUSCLES = _MUSCLES
EQUIPMENT = _EQUIPMENT
MOVEMENT_PATTERNS = _MOVEMENT_PATTERNS
DIFFICULTIES = _DIFFICULTIES
