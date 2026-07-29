"""Routes de sauvegarde et de restauration de la base Marvin."""

import asyncio

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field, StrictBool

import backup
from database_bootstrap import initialize_database
import memory_lifecycle
import memory_recovery
import full_backup
from http_idempotency import IDEMPOTENCY_RESPONSES, IdempotencyKey, execute as execute_idempotent


router = APIRouter(tags=["backups"])
_restore_lock = asyncio.Lock()


@router.get("/api/backups")
async def list_backups():
    return backup.list_backups()


@router.get("/api/backups/full")
async def list_full_backups():
    return await asyncio.to_thread(full_backup.list_backups)


@router.post("/api/backups/full")
async def create_full_backup():
    return await asyncio.to_thread(full_backup.create)


@router.post("/api/backups/full/{filename}/verify")
async def verify_full_backup(
    filename: str = Path(
        min_length=39,
        max_length=64,
        pattern=r"^marvin_full_\d{8}_\d{6}_\d{6}\.mrvfull$",
    ),
):
    try:
        return await asyncio.to_thread(full_backup.verify, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Bundle global introuvable.") from exc


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


@router.post("/api/backups/restore", responses=IDEMPOTENCY_RESPONSES)
async def restore_backup_now(body: RestoreRequest, idempotency_key: IdempotencyKey = None):
    # Cette route reste hors du registre d'outils : le LLM ne peut pas la piloter.
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirmed=true).")
    async def restore_once():
        async with _restore_lock:
            result = await memory_recovery.restore_and_reconcile(
                body.filename,
                restore=backup.restore_backup,
                initialize=initialize_database,
                repair=memory_lifecycle.repair_consistency,
            )
        if result.get("error"):
            status = {
                "backup_not_found": 404,
                "invalid_backup": 409,
            }.get(result.get("error_code"), 500)
            raise HTTPException(status_code=status, detail=result["error"])
        return result

    return await execute_idempotent(
        operation_name="http_backup_restore",
        payload=body.model_dump(),
        operation=restore_once,
        idempotency_key=idempotency_key,
    )
