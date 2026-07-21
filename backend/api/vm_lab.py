"""Read-only VM lab state and explicit ISO integrity verification."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import vm_lab
import vm_lab_jobs


router = APIRouter(prefix="/api/vm-lab", tags=["vm-lab"])


class VerifyRequest(BaseModel):
    confirmed: bool = False


class InstallRequest(BaseModel):
    profile: str
    confirmed: bool = False


@router.get("/status")
async def vm_lab_status():
    return vm_lab.status()


@router.post("/verify-isos")
async def vm_lab_verify_isos(payload: VerifyRequest):
    try:
        return vm_lab.verify_isos(confirmed=payload.confirmed)
    except (OSError, ValueError, vm_lab.VMLabError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/install")
async def vm_lab_install_status():
    return vm_lab_jobs.status()


@router.post("/install")
async def vm_lab_install(payload: InstallRequest):
    try:
        return vm_lab_jobs.start(payload.profile, confirmed=payload.confirmed)
    except (OSError, ValueError, vm_lab.VMLabError, vm_lab_jobs.VMLabJobError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
