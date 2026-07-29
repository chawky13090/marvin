"""Routes de gestion et de consolidation des souvenirs Marvin."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

import database as db
import memory_lifecycle


router = APIRouter(tags=["memories"])


@router.get("/api/memories")
async def list_memories():
    return db.get_memories()


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    category: Literal["user_profile", "preference", "fact", "habit"] = "fact"


@router.post("/api/memories")
async def create_memory(body: MemoryCreate):
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content requis")
    return await memory_lifecycle.create(
        body.content.strip(),
        body.category.strip(),
        source="api",
    )


@router.delete("/api/memories")
async def clear_memories(confirmed: bool = Query(default=False)):
    if not confirmed:
        raise HTTPException(
            status_code=409,
            detail="Confirmation explicite requise pour oublier tous les souvenirs.",
        )
    result = await memory_lifecycle.clear_all()
    if not result["success"]:
        raise HTTPException(status_code=503, detail=result)
    return result


@router.delete("/api/memories/{mid}")
async def delete_memory(mid: str = Path(min_length=1, max_length=128)):
    result = await memory_lifecycle.forget(mid)
    if not result["success"]:
        raise HTTPException(status_code=503, detail=result)
    return result


@router.get("/api/memories/consolidate/preview")
async def preview_memory_consolidation():
    """Aperçu des fusions proposées, sans suppression."""
    import memory_consolidation

    return await memory_consolidation.consolidate_memories(dry_run=True)


@router.post("/api/memories/consolidate")
async def run_memory_consolidation():
    """Fusionne immédiatement les souvenirs en doublon."""
    import memory_consolidation

    return await memory_consolidation.consolidate_memories(dry_run=False)


@router.get("/api/memories/consistency")
async def memory_consistency():
    return memory_lifecycle.audit_consistency()


@router.post("/api/memories/consistency/repair")
async def repair_memory_consistency(
    confirmed: bool = Query(default=False),
    dry_run: bool = Query(default=True),
):
    if not dry_run and not confirmed:
        raise HTTPException(
            status_code=409,
            detail="Confirmation explicite requise pour réparer les projections mémoire.",
        )
    result = await memory_lifecycle.repair_consistency(dry_run=dry_run)
    if not result["success"]:
        raise HTTPException(status_code=503, detail=result)
    return result
