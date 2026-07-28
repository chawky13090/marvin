"""Routes de sauvegarde et de restauration de la base Marvin."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictBool

import backup


router = APIRouter(tags=["backups"])


@router.get("/api/backups")
async def list_backups():
    return backup.list_backups()


@router.post("/api/backups")
async def create_backup_now():
    result = await asyncio.to_thread(backup.create_backup)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


class RestoreRequest(BaseModel):
    filename: str = Field(
        min_length=28,
        max_length=64,
        pattern=r"^secretary_\d{8}_\d{6}(?:_\d{6})?(?:_\d+)?\.(?:db|mrvbak)$",
    )
    confirmed: StrictBool = False


@router.post("/api/backups/restore")
async def restore_backup_now(body: RestoreRequest):
    # Cette route reste hors du registre d'outils : le LLM ne peut pas la piloter.
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirmed=true).")
    result = await asyncio.to_thread(backup.restore_backup, body.filename)
    if result.get("error"):
        status = {
            "backup_not_found": 404,
            "invalid_backup": 409,
        }.get(result.get("error_code"), 500)
        raise HTTPException(status_code=status, detail=result["error"])
    return result
