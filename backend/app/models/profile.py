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
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.database import Base


class Profile(Base):
    """spec §4.3 -- the Settings data. One-to-one with users, no surrogate key (P1-ADR-03).
    A user with no profile row means onboarding is unfinished; that is a legitimate state.
    """

    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 2 AND 60", name="chk_profiles_name_length"
        ),
        CheckConstraint("gender IN ('male', 'female')", name="chk_profiles_gender"),
        # Drives P1-SAF-001 (a user under 18 cannot select 'lose'), enforced separately in
        # the service layer -- this CHECK only guards the account-holder age floor/ceiling.
        CheckConstraint(
            "birth_date <= current_date - INTERVAL '13 years' AND "
            "birth_date >= current_date - INTERVAL '100 years'",
            name="chk_profiles_birth_date",
        ),
        CheckConstraint("height_cm BETWEEN 100 AND 250", name="chk_profiles_height_cm"),
        CheckConstraint("weight_kg BETWEEN 30 AND 300", name="chk_profiles_weight_kg"),
        CheckConstraint("goal IN ('lose', 'gain', 'maintain')", name="chk_profiles_goal"),
        CheckConstraint(
            "experience_level IN ('beginner', 'intermediate', 'advanced')",
            name="chk_profiles_experience_level",
        ),
        CheckConstraint(
            "activity_level IN ('sedentary', 'light', 'moderate', 'high', 'very_high')",
            name="chk_profiles_activity_level",
        ),
        CheckConstraint("unit_system IN ('metric', 'imperial')", name="chk_profiles_unit_system"),
        CheckConstraint("language IN ('ar', 'en')", name="chk_profiles_language"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    gender: Mapped[str] = mapped_column(Text, nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    height_cm: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    # Nullable: marked [confirm] in spec §13.1, unresolved (weight_kg/activity_level in
    # onboarding). Nullable accommodates either answer cleanly without a further migration.
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    experience_level: Mapped[str] = mapped_column(Text, nullable=False)
    activity_level: Mapped[str | None] = mapped_column(Text)
    unit_system: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'metric'"))
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ar'"))
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Phase 2 §4.2, added by T-15's migration at the database level only. T-18 is the
    # first consumer -- workout_sessions.local_date cannot be computed without it --
    # and wires the ORM attribute plus the PATCH /profile editable-field list. IANA
    # name, editable in Settings; T-23 sends the device zone from the client.
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Africa/Cairo'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
