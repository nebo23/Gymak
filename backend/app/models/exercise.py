from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, CheckConstraint, DateTime, Text, UniqueConstraint, func, text
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
    """spec §4.1, P2-ADR-02. Seeded reference data, owned by a migration (T-16) -- no
    endpoint creates, edits, or deletes a row. `id` is not app-generated (no Python-side
    default): the seed file carries a fixed UUID v7 per row so the same exercise resolves
    to the same id in every environment. Read-only for the app role (§4.10: SELECT only,
    no RLS policy -- this is public reference data with no user_id).
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
