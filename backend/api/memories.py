"""Routes de gestion et de consolidation des souvenirs Marvin."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database as db


router = APIRouter(tags=["memories"])


@router.get("/api/memories")
async def list_memories():
    return db.get_memories()


class MemoryCreate(BaseModel):
    content: str
    category: str = "fact"


@router.post("/api/memories")
async def create_memory(body: MemoryCreate):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content requis")
    return db.create_memory(body.content, body.category)


@router.delete("/api/memories")
async def clear_memories():
    db.clear_all_memories()
    return {"success": True}


@router.delete("/api/memories/{mid}")
async def delete_memory(mid: str):
    db.delete_memory(mid)
    return {"success": True}


@router.get("/api/memories/consolidate/preview")
async def preview_memory_consolidation():
    """Aperçu des fusions proposées, sans suppression."""
    import memory_consolidation

    return memory_consolidation.consolidate_memories(dry_run=True)


@router.post("/api/memories/consolidate")
async def run_memory_consolidation():
    """Fusionne immédiatement les souvenirs en doublon."""
    import memory_consolidation

    return memory_consolidation.consolidate_memories(dry_run=False)
