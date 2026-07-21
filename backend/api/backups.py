"""Routes de sauvegarde et de restauration de la base Marvin."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    filename: str
    confirmed: bool = False


@router.post("/api/backups/restore")
async def restore_backup_now(body: RestoreRequest):
    # Cette route reste hors du registre d'outils : le LLM ne peut pas la piloter.
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirmed=true).")
    result = await asyncio.to_thread(backup.restore_backup, body.filename)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result
