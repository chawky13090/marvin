"""API Marvin Forge : corpus, notation déterministe et métriques de fiabilité."""
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import forge
import frontier_arena


router = APIRouter(prefix="/api/forge", tags=["forge"])


class ScenarioPayload(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="general", max_length=60)
    description: str = Field(default="", max_length=500)
    prompt: str = Field(min_length=1, max_length=12000)
    model: str | None = Field(default=None, max_length=160)
    cortex: dict[str, Any] = Field(default_factory=dict)
    expectations: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    source: str = Field(default="manual", max_length=120)


class GradePayload(BaseModel):
    scenario_id: str = Field(min_length=3, max_length=64)
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    persist: bool = True


class ArenaSource(BaseModel):
    citation: str | None = Field(default=None, max_length=80)
    citations: list[str] = Field(default_factory=list, max_length=50)
    title: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=4000)
    excerpt: str = Field(default="", max_length=12000)
    published_at: str | None = Field(default=None, max_length=80)


class ArenaSubmissionPayload(BaseModel):
    scenario_id: str = Field(min_length=3, max_length=64)
    system: str = Field(min_length=1, max_length=120)
    answer: str = Field(min_length=1, max_length=100_000)
    sources: list[ArenaSource] = Field(default_factory=list, max_length=200)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    cost: float | None = Field(default=None, ge=0, le=1_000_000)
    human_interventions: int = Field(default=0, ge=0, le=10000)
    privacy_violations: int = Field(default=0, ge=0, le=10000)
    notes: str = Field(default="", max_length=1000)


class ArenaMatchPayload(BaseModel):
    scenario_id: str | None = Field(default=None, max_length=64)
    submission_ids: list[str] = Field(default_factory=list, max_length=2)


class ArenaScorecard(BaseModel):
    correctness: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    evidence: int = Field(ge=1, le=5)
    usefulness: int = Field(ge=1, le=5)


class ArenaVotePayload(BaseModel):
    winner: str = Field(min_length=1, max_length=3)
    scores: dict[str, ArenaScorecard]
    notes: str = Field(default="", max_length=1000)


@router.get("/scenarios")
async def scenarios_list():
    return {"scenarios": forge.list_scenarios()}


@router.post("/scenarios")
async def scenarios_save(payload: ScenarioPayload):
    try:
        return {"success": True, "scenario": forge.save_scenario(payload.model_dump(exclude_none=True))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/scenarios/{scenario_id}")
async def scenarios_delete(scenario_id: str):
    if not forge.delete_scenario(scenario_id):
        raise HTTPException(status_code=404, detail="Scénario Forge introuvable.")
    return {"success": True}


@router.post("/grade")
async def grade(payload: GradePayload):
    scenario = forge.get_scenario(payload.scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scénario Forge introuvable.")
    if payload.persist:
        return {"run": forge.record_run(payload.scenario_id, payload.events, duration_ms=payload.duration_ms)}
    return {"grade": forge.grade_trace(scenario, payload.events, duration_ms=payload.duration_ms)}


@router.get("/runs")
async def runs_list(
    limit: int = Query(default=200, ge=1, le=2000),
    scenario_id: str | None = Query(default=None, max_length=64),
):
    return {"runs": forge.list_runs(limit=limit, scenario_id=scenario_id)}


@router.get("/summary")
async def forge_summary():
    return forge.summary()


@router.post("/arena/submissions")
async def arena_submission_create(payload: ArenaSubmissionPayload):
    try:
        return {"submission": frontier_arena.submit(
            scenario_id=payload.scenario_id,
            system=payload.system,
            answer=payload.answer,
            sources=[item.model_dump(exclude_none=True) for item in payload.sources],
            duration_ms=payload.duration_ms,
            cost=payload.cost,
            human_interventions=payload.human_interventions,
            privacy_violations=payload.privacy_violations,
            notes=payload.notes,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/arena/submissions")
async def arena_submissions_list(
    limit: int = Query(default=200, ge=1, le=5000),
    scenario_id: str | None = Query(default=None, max_length=64),
):
    return {"submissions": frontier_arena.list_submissions(limit=limit, scenario_id=scenario_id)}


@router.get("/arena/leaderboard")
async def arena_leaderboard():
    return frontier_arena.leaderboard()


@router.post("/arena/matches")
async def arena_match_create(payload: ArenaMatchPayload):
    try:
        return {"match": frontier_arena.create_blind_match(
            scenario_id=payload.scenario_id,
            submission_ids=payload.submission_ids or None,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/arena/matches/stats")
async def arena_match_stats():
    return frontier_arena.blind_stats()


@router.get("/arena/matches/{match_id}")
async def arena_match_detail(match_id: str):
    match = frontier_arena.get_blind_match(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Duel Arena introuvable.")
    return {"match": match}


@router.post("/arena/matches/{match_id}/vote")
async def arena_match_vote(match_id: str, payload: ArenaVotePayload):
    try:
        return {"match": frontier_arena.vote_blind_match(
            match_id,
            winner=payload.winner,
            scores={slot: values.model_dump() for slot, values in payload.scores.items()},
            notes=payload.notes,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
