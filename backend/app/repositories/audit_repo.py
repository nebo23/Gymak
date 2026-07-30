"""Append-only audit log data access. §4.6: the app role holds INSERT and SELECT only --
nothing here ever UPDATEs or DELETEs a row.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record(
    session: AsyncSession,
    *,
    action: str,
    actor_user_id: uuid.UUID | None,
    entity: str | None = None,
    entity_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Insert one audit row. `actor_user_id` is nullable by design (§4.6): a failed login
    against an unknown email has no user to attribute it to.
    """
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        event_metadata=metadata or {},
        ip=ip,
        user_agent=user_agent,
    )
    session.add(entry)
    await session.flush()
    return entry
