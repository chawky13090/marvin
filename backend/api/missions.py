"""API de lecture et de checkpoint de Mission OS."""
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import mission_os


router = APIRouter(prefix="/api/missions", tags=["missions"])


class CheckpointPayload(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    state: dict[str, Any] = Field(default_factory=dict)

class ReasonPayload(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.get("")
async def missions_list(
    limit: int = Query(default=100, ge=1, le=1000),
    status: str | None = Query(default=None, max_length=30),
):
    return {"missions": mission_os.list_missions(limit=limit, status=status)}


@router.get("/{mission_id}")
async def mission_detail(mission_id: str):
    mission = mission_os.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission introuvable.")
    return {"mission": mission, "events": mission_os.list_events(mission_id=mission_id, limit=500)}


@router.get("/{mission_id}/events")
async def mission_events(mission_id: str, limit: int = Query(default=500, ge=1, le=5000)):
    if mission_os.get_mission(mission_id) is None:
        raise HTTPException(status_code=404, detail="Mission introuvable.")
    return {"events": mission_os.list_events(mission_id=mission_id, limit=limit)}


@router.post("/{mission_id}/checkpoints")
async def mission_checkpoint(mission_id: str, payload: CheckpointPayload):
    mission = mission_os.checkpoint(mission_id, payload.label, payload.state)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission introuvable.")
    return {"success": True, "mission": mission}


@router.post("/{mission_id}/pause")
async def mission_pause(mission_id: str, payload: ReasonPayload):
    mission = mission_os.pause_mission(mission_id, payload.reason or "pause demandée")
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission introuvable.")
    return {"success": True, "mission": mission}


@router.post("/{mission_id}/resume")
async def mission_resume(mission_id: str):
    mission = mission_os.resume_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=409, detail="Mission non reprenable.")
    return {"success": True, "mission": mission}


@router.post("/{mission_id}/steps/{step_index}/retry")
async def mission_retry_step(mission_id: str, step_index: int):
    mission = mission_os.retry_step(mission_id, step_index)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission ou étape introuvable.")
    return {"success": True, "mission": mission}
