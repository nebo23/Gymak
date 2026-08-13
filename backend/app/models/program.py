from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.ids import new_id
from app.database import Base


class Program(Base):
    """spec §4.3. A generated plan (P2-ADR-01). `goal`/`experience_level` are snapshots
    of the profile at generation time, not a join -- a user who changes their goal in
    Settings has not retroactively changed the plan they have been following. Old
    programs are kept: regeneration sets `is_current = false` and `superseded_at` on the
    previous row rather than deleting it, so sessions logged against its days keep
    resolving. The partial unique index below is the "exactly one true per user"
    invariant §4.3 states in prose, enforced the same way §4.6's `ux_one_active_session`
    is -- in the database, not the service.
    """

    __tablename__ = "programs"
    __table_args__ = (
        CheckConstraint("days_per_week BETWEEN 2 AND 6", name="chk_programs_days_per_week"),
        CheckConstraint(
            "split_type IN ('full_body', 'upper_lower', 'push_pull_legs')",
            name="chk_programs_split_type",
        ),
        CheckConstraint("goal IN ('lose', 'gain', 'maintain')", name="chk_programs_goal"),
        CheckConstraint(
            "experience_level IN ('beginner', 'intermediate', 'advanced')",
            name="chk_programs_experience_level",
        ),
        Index(
            "ux_one_current_program",
            "user_id",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    days_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    split_type: Mapped[str] = mapped_column(Text, nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    experience_level: Mapped[str] = mapped_column(Text, nullable=False)
    generator_version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProgramDay(Base):
    """spec §4.4. `day_index` is an ordinal within the week (1-based), not a weekday --
    the user trains on their own days, so the streak counts sessions, not calendar
    adherence. No `user_id` column: ownership reads through `program_id` (P2-ADR-09),
    the same parent-EXISTS pattern §4.10 spells out for `workout_sets`.
    """

    __tablename__ = "program_days"
    __table_args__ = (
        CheckConstraint("day_index BETWEEN 1 AND 6", name="chk_program_days_day_index"),
        UniqueConstraint("program_id", "day_index", name="uq_program_days_program_day_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    program_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # An i18n key ("plan.day.upper"), never a translated string -- the server never sends
    # display text (Phase 1 §9.6).
    label_key: Mapped[str] = mapped_column(Text, nullable=False)
    focus_muscles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)


class ProgramExercise(Base):
    """spec §4.5. `exercise_id` is `ON DELETE RESTRICT`, not `CASCADE` -- P2-ADR-02 says
    exercises are never deleted, and this constraint is what makes that a guarantee
    rather than a promise. No `user_id` column: ownership reads through
    `program_day_id` -> `program_id` (P2-ADR-09).
    """

    __tablename__ = "program_exercises"
    __table_args__ = (
        CheckConstraint("target_sets BETWEEN 1 AND 8", name="chk_program_exercises_target_sets"),
        CheckConstraint(
            "target_reps_min >= 1 AND target_reps_min <= target_reps_max AND target_reps_max <= 30",
            name="chk_program_exercises_target_reps",
        ),
        CheckConstraint(
            "rest_seconds BETWEEN 30 AND 300", name="chk_program_exercises_rest_seconds"
        ),
        UniqueConstraint("program_day_id", "position", name="uq_program_exercises_day_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    program_day_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("program_days.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    target_sets: Mapped[int] = mapped_column(Integer, nullable=False)
    target_reps_min: Mapped[int] = mapped_column(Integer, nullable=False)
    target_reps_max: Mapped[int] = mapped_column(Integer, nullable=False)
    rest_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
