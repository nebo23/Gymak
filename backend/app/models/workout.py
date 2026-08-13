from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.ids import new_id
from app.database import Base


class WorkoutSession(Base):
    """spec §4.6, P2-ADR-03. A small state machine: in_progress -> completed | abandoned,
    no other transitions. `ux_one_active_session` is the "at most one in_progress session
    per user" invariant, enforced in the database rather than the service. `local_date` is
    `started_at` resolved into the user's §4.2 timezone at insert -- stored so the streak
    never re-derives a timezone at read time.
    """

    __tablename__ = "workout_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'abandoned')",
            name="chk_workout_sessions_status",
        ),
        Index(
            "ux_one_active_session",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # NULL for an empty session (P2-FR-005). SET NULL, not CASCADE: deleting an old
    # program must never delete the sessions logged against its days.
    program_day_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("program_days.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Computed at finish as last_logged_at - started_at, not ended_at - started_at (§5.8):
    # stored here only, as a finish-time snapshot.
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    total_volume_kg: Mapped[Decimal | None] = mapped_column(Numeric(9, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)


class WorkoutSet(Base):
    """spec §4.7, P2-ADR-04. Stores only absolute values -- e1RM, volume, and every
    personal record are computed on read, never stored (P2-ADR-05). No `user_id` column:
    ownership reads through `session_id` (P2-ADR-09), and the owning policy must prove a
    set belonging to another user's session is invisible even when its own id is known.
    """

    __tablename__ = "workout_sets"
    __table_args__ = (
        CheckConstraint("reps BETWEEN 1 AND 100", name="chk_workout_sets_reps"),
        CheckConstraint("weight_kg BETWEEN 0 AND 500", name="chk_workout_sets_weight_kg"),
        CheckConstraint("rpe IS NULL OR rpe BETWEEN 5 AND 10", name="chk_workout_sets_rpe"),
        UniqueConstraint(
            "session_id", "exercise_id", "set_index", name="uq_workout_sets_session_exercise_index"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False
    )
    # 1-based, per exercise within the session. Assigned server-side, never accepted from
    # the client (§5.7) -- a client-assigned index is a race the moment a retry duplicates
    # a request.
    set_index: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    is_warmup: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
