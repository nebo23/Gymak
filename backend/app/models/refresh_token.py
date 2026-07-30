from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.ids import new_id
from app.database import Base


class RefreshToken(Base):
    """spec §4.4. One row per issued token; family_id ties a rotation chain to one
    device session (P1-ADR-02). Only token_hash is ever stored -- the raw value exists
    once, in the response body.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index(
            "idx_rt_user_active",
            "user_id",
            postgresql_where=text("consumed_at IS NULL AND revoked_at IS NULL"),
        ),
        Index("idx_rt_family", "family_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
