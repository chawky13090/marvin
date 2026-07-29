"""API Model Market et Research Swarm."""
from typing import Any

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

import model_market
import research_swarm
import swarm_jobs
import research_export


router = APIRouter(prefix="/api/model-market", tags=["model-market"])


class SwarmRequest(BaseModel):
    question: str = Field(min_length=3, max_length=12000)
    agent_count: int = Field(default=5, ge=3, le=5)
    sources_per_agent: int = Field(default=3, ge=1, le=8)
    max_duration_seconds: int = Field(default=600, ge=60, le=3600)
    engine_version: str = Field(default="auto", pattern=r"^(auto|v2|v3)$")
    depth: str | None = Field(default=None, pattern=r"^(quick|deep|exhaustive)$")
    language: str = Field(default="fr-FR", min_length=2, max_length=12)
    region: str = Field(default="FR", min_length=2, max_length=2)
    freshness: str | None = Field(default=None, pattern=r"^(day|week|month|year)$")
    source_policy: str = Field(
        default="balanced",
        pattern=r"^(balanced|primary_first|academic|official_only)$",
    )
    preferred_domains: list[str] = Field(default_factory=list, max_length=50)
    excluded_domains: list[str] = Field(default_factory=list, max_length=50)
    deliverable: str = Field(
        default="report",
        pattern=r"^(answer|report|comparison|brief)$",
    )

    def research_options(self) -> dict[str, Any]:
        return {
            "depth": self.depth,
            "language": self.language,
            "region": self.region,
            "freshness": self.freshness,
            "source_policy": self.source_policy,
            "preferred_domains": self.preferred_domains,
            "excluded_domains": self.excluded_domains,
            "deliverable": self.deliverable,
        }


class CloudModelPullRequest(BaseModel):
    model: str = Field(min_length=3, max_length=210)


class SwarmSteerRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


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
    return {
        "observations": model_market.list_observations(limit),
        "evidence_integrity": model_market.evidence_integrity(),
    }


@router.get("/integrity")
async def market_integrity():
    return model_market.evidence_integrity()


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
    return {
        "runs": research_swarm.list_runs(limit),
        "evidence_integrity": research_swarm.evidence_integrity(),
    }


@router.get("/swarm/integrity")
async def swarm_integrity():
    return research_swarm.evidence_integrity()


@router.get("/swarm/runs/{run_id}/export")
async def swarm_run_export(
    run_id: str,
    format_name: str = Query(alias="format", pattern=r"^(md|json|docx|pdf)$"),
):
    run = next(
        (row for row in research_swarm.list_runs(200) if row.get("id") == run_id),
        None,
    )
    if not run:
        raise HTTPException(status_code=404, detail="Recherche introuvable.")
    try:
        content, media_type, filename = research_export.export_run(run, format_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/swarm/run")
async def swarm_run(payload: SwarmRequest) -> dict[str, Any]:
    return await research_swarm.execute(
        payload.question,
        agent_count=payload.agent_count,
        sources_per_agent=payload.sources_per_agent,
        max_duration_seconds=payload.max_duration_seconds,
        engine_version=payload.engine_version,
        research_options=payload.research_options(),
    )


@router.get("/swarm/jobs")
async def swarm_jobs_list(limit: int = Query(default=100, ge=1, le=500)):
    return {"jobs": swarm_jobs.list_jobs(limit)}


@router.post("/swarm/jobs")
async def swarm_job_create(payload: SwarmRequest):
    return {"job": swarm_jobs.create_job(
        payload.question, payload.agent_count, payload.sources_per_agent,
        payload.max_duration_seconds, engine_version=payload.engine_version,
        research_options=payload.research_options(),
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


@router.post("/swarm/jobs/{job_id}/steer")
async def swarm_job_steer(job_id: str, payload: SwarmSteerRequest):
    try:
        job = swarm_jobs.steer_job(job_id, payload.query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=409, detail="Cette recherche ne peut plus être réorientée.")
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
