"""Portable storage layout for runtime assets, virtual machines and user exports."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import storage_layout


router = APIRouter(prefix="/api/storage", tags=["storage"])


class StorageConfigureRequest(BaseModel):
    machine_root: str = Field(min_length=3, max_length=1_000)
    export_root: str = Field(min_length=3, max_length=1_000)
    confirmed: bool = False


class StorageEnsureRequest(BaseModel):
    confirmed: bool = False


@router.get("/layout")
async def storage_status():
    return storage_layout.status()


@router.post("/layout/configure")
async def storage_configure(payload: StorageConfigureRequest):
    try:
        return storage_layout.configure(
            machine_root=payload.machine_root,
            export_root=payload.export_root,
            confirmed=payload.confirmed,
        )
    except (OSError, ValueError, storage_layout.StorageLayoutError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/layout/ensure")
async def storage_ensure(payload: StorageEnsureRequest):
    try:
        return storage_layout.ensure(confirmed=payload.confirmed)
    except (OSError, ValueError, storage_layout.StorageLayoutError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
