from __future__ import annotations

from fastapi import APIRouter

from app.database import database_is_reachable

router = APIRouter(tags=["health"])


@router.get("/health")
async def get_health() -> dict[str, str]:
    db_reachable = await database_is_reachable()
    return {
        "status": "ok" if db_reachable else "degraded",
        "database": "reachable" if db_reachable else "unreachable",
    }
