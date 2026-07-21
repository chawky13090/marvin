"""Routes du diagnostic deterministe Marvin Doctor."""

from fastapi import APIRouter, Body, HTTPException

import doctor as doctor_service


router = APIRouter(tags=["doctor"])


@router.get("/api/doctor")
async def get_doctor():
    return await doctor_service.run_diagnostics()


@router.post("/api/doctor/fix")
async def doctor_fix(body: dict = Body(...)):
    fix_id = (body.get("fix") or "").strip()
    if not fix_id:
        raise HTTPException(status_code=400, detail="Correctif (fix) requis.")
    result = await doctor_service.apply_fix(fix_id)
    result["diagnostics"] = await doctor_service.run_diagnostics()
    return result
