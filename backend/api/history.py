"""Routes de consultation de l'historique et de la fiabilité des outils."""

from fastapi import APIRouter

import database as db


router = APIRouter(tags=["history"])


@router.get("/api/history")
async def list_history(tool_name: str | None = None, limit: int = 50, offset: int = 0):
    return db.list_executions(tool_name=tool_name, limit=limit, offset=offset)


@router.get("/api/history/stats")
async def history_stats():
    return db.get_execution_stats()


@router.get("/api/history/reliability")
async def history_reliability(min_calls: int = 3, days: int = 90, recent_days: int = 7):
    """Expose les taux d'échec globaux et récents, regroupés par outil."""
    return {
        "tools": db.get_tool_reliability(
            min_calls=min_calls,
            days=days,
            recent_days=recent_days,
        )
    }
