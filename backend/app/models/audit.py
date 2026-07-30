from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Text, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.ids import new_id
from app.database import Base


class AuditLog(Base):
    """spec §4.6. Append-only; the app role is granted INSERT and SELECT only, no UPDATE
    or DELETE, enforced by GRANT in the migration rather than by convention.

    entity/entity_id are a loose, polymorphic reference (action names the kind of entity)
    and deliberately carry no foreign key -- no single table could be the FK target.
    actor_user_id is deliberately unconstrained too, for a sharper reason than entity_id:
    spec §4.6 never asks for a real FK here, and a real one would actively break the
    table's own append-only design. ON DELETE SET NULL/CASCADE both require UPDATE or
    DELETE privilege on audit_log to fire -- exactly the privilege the app role is
    deliberately never granted (confirmed empirically: with the FK in place, deleting a
    user under the app role failed with "permission denied for table audit_log", because
    Postgres has to touch this table to honour the FK action). An audit row must outlive
    the account it recorded regardless, so a logical, unenforced reference is also the
    more correct choice, not just the one that avoids the privilege conflict.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=new_id)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    # Python attribute can't be named `metadata` -- it collides with the declarative
    # base's own reserved MetaData accessor. The DB column is still named `metadata`.
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
