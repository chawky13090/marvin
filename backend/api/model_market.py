"""API Model Market et Research Swarm."""
from typing import Any

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import model_market
import research_swarm
import swarm_jobs


router = APIRouter(prefix="/api/model-market", tags=["model-market"])


class SwarmRequest(BaseModel):
    question: str = Field(min_length=3, max_length=12000)
    agent_count: int = Field(default=5, ge=3, le=5)
    sources_per_agent: int = Field(default=3, ge=1, le=5)
    max_duration_seconds: int = Field(default=600, ge=60, le=1800)


class CloudModelPullRequest(BaseModel):
    model: str = Field(min_length=3, max_length=210)


@router.get("/catalog")
async def market_catalog(need: str = Query(default="general", max_length=30)):
    return model_market.catalog(need)


@router.get("/recommend")
async def market_recommend(
    need: str = Query(default="general", max_length=30),
    count: int = Query(default=1, ge=1, le=10),
    distinct_families: bool = False,
):
    return {"need": need, "recommendations": model_market.recommend(
        need, count=count, distinct_families=distinct_families,
    )}


@router.get("/observations")
async def market_observations(limit: int = Query(default=200, ge=1, le=2000)):
    return {"observations": model_market.list_observations(limit)}


@router.get("/fleet")
async def cloud_fleet_status():
    return model_market.fleet_status()


@router.post("/fleet/sync")
async def cloud_fleet_sync():
    return await model_market.sync_recommended_cloud_models()


@router.post("/fleet/pull")
async def cloud_fleet_pull(payload: CloudModelPullRequest):
    try:
        result = await model_market.pull_cloud_model(payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result)
    return result


@router.get("/swarm/runs")
async def swarm_runs(limit: int = Query(default=30, ge=1, le=200)):
    return {"runs": research_swarm.list_runs(limit)}


@router.post("/swarm/run")
async def swarm_run(payload: SwarmRequest) -> dict[str, Any]:
    return await research_swarm.execute(
        payload.question,
        agent_count=payload.agent_count,
        sources_per_agent=payload.sources_per_agent,
        max_duration_seconds=payload.max_duration_seconds,
    )


@router.get("/swarm/jobs")
async def swarm_jobs_list(limit: int = Query(default=100, ge=1, le=500)):
    return {"jobs": swarm_jobs.list_jobs(limit)}


@router.post("/swarm/jobs")
async def swarm_job_create(payload: SwarmRequest):
    return {"job": swarm_jobs.create_job(
        payload.question, payload.agent_count, payload.sources_per_agent,
        payload.max_duration_seconds,
    )}


@router.get("/swarm/jobs/{job_id}")
async def swarm_job_detail(job_id: str):
    job = swarm_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job Research Swarm introuvable.")
    return {"job": job}


@router.delete("/swarm/jobs/{job_id}")
async def swarm_job_cancel(job_id: str):
    job = swarm_jobs.cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job Research Swarm introuvable.")
    return {"success": True, "job": job}


@router.post("/swarm/jobs/{job_id}/resume")
async def swarm_job_resume(job_id: str):
    job = swarm_jobs.resume_job(job_id)
    if not job:
        raise HTTPException(status_code=409, detail="Ce job ne peut pas être repris.")
    return {"success": True, "job": job}


@router.get("/swarm/jobs/{job_id}/stream")
async def swarm_job_stream(job_id: str):
    if not swarm_jobs.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job Research Swarm introuvable.")
    async def generate():
        previous = None
        while True:
            job = swarm_jobs.get_job(job_id)
            payload = json.dumps(job, ensure_ascii=False)
            if payload != previous:
                yield f"data: {payload}\n\n"
                previous = payload
            if job.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                break
            await asyncio.sleep(0.75)
    return StreamingResponse(generate(), media_type="text/event-stream")
