from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.ids import new_id
from app.database import Base


class UserIdentity(Base):
    """spec §4.2. A social identity hanging off a users row (P1-ADR-01)."""

    __tablename__ = "user_identities"
    __table_args__ = (
        # 'apple' is allowed by the check now, ahead of use, so the Phase 3 addition of
        # Apple Sign-In needs no migration (spec 4.2 note).
        CheckConstraint(
            "provider IN ('google', 'facebook', 'apple')",
            name="chk_user_identities_provider",
        ),
        UniqueConstraint("provider", "provider_uid", name="uq_user_identities_provider_uid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_uid: Mapped[str] = mapped_column(Text, nullable=False)
    firebase_uid: Mapped[str] = mapped_column(Text, nullable=False)
    email_at_provider: Mapped[str | None] = mapped_column(CITEXT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
