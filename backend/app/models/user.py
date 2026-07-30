from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.ids import new_id
from app.database import Base


class User(Base):
    """spec §4.1. Identity and credentials only -- no profile/domain data (P1-ADR-03)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "password_hash IS NOT NULL OR email_verified = true",
            name="chk_credential_present",
        ),
        # Partial, not a blanket UNIQUE: a soft-deleted row's email must be reusable by a
        # new registration (spec 4.1: "A row with deleted_at IS NOT NULL is invisible to
        # every query except the purge job"). A blanket UNIQUE on email would silently
        # block that reuse, so only the live rows are covered here.
        Index(
            "uq_users_email_live",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
