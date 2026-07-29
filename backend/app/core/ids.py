from __future__ import annotations

import uuid

from uuid6 import uuid7


def new_id() -> uuid.UUID:
    """UUID v7, generated here and passed explicitly on insert (spec P1-ADR-06)."""
    return uuid7()
