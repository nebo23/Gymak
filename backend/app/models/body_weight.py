from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.ids import new_id
from app.database import Base


class BodyWeightEntry(Base):
    """spec §4.8, P2-ADR-06. One row per user per calendar day; a second entry for the
    same date is an upsert, not an error (the user stepped on the scale twice, and the
    later reading is the one they meant). `profiles.weight_kg` is kept in sync with the
    most recent entry, written in the same transaction as the entry itself -- that
    bookkeeping lives in the service layer (T-20), not here.
    """

    __tablename__ = "body_weight_entries"
    __table_args__ = (
        CheckConstraint("weight_kg BETWEEN 30 AND 300", name="chk_body_weight_entries_weight_kg"),
        UniqueConstraint("user_id", "measured_on", name="uq_body_weight_entries_user_measured_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    measured_on: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
