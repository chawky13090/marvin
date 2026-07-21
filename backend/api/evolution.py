"""API Evolution Lab."""
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import evolution_lab

router = APIRouter(prefix="/api/evolution", tags=["evolution"])

class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=80)
    candidate_value: int
    hypothesis: str = Field(default="", max_length=1000)

class Evaluation(BaseModel):
    baseline_trials: list[dict[str, Any]] = Field(min_length=3, max_length=100)
    candidate_trials: list[dict[str, Any]] = Field(min_length=3, max_length=100)

class Confirmation(BaseModel):
    confirmed: bool = False

@router.get("/experiments")
async def experiments(limit: int = Query(default=100, ge=1, le=500)):
    return {"experiments": evolution_lab.list_experiments(limit), "allowed_targets": evolution_lab.ALLOWED_TARGETS}

@router.post("")
async def create(payload: ExperimentCreate):
    try: return {"experiment": evolution_lab.create(payload.name, payload.target, payload.candidate_value, payload.hypothesis)}
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/{experiment_id}/evaluate")
async def evaluate(experiment_id: str, payload: Evaluation):
    try: return {"experiment": evolution_lab.evaluate(experiment_id, payload.baseline_trials, payload.candidate_trials)}
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/{experiment_id}/promote")
async def promote(experiment_id: str, payload: Confirmation):
    try: return {"experiment": evolution_lab.promote(experiment_id, payload.confirmed)}
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/{experiment_id}/rollback")
async def rollback(experiment_id: str, payload: Confirmation):
    try: return {"experiment": evolution_lab.rollback(experiment_id, payload.confirmed)}
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
