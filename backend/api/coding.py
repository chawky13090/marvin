"""Supervision API for durable, isolated coding projects and engineering knowledge."""
import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import coding_mission
import coding_jobs
import coding_workspace
import coding_service
import engineering_radar
import language_registry
import repository_intelligence
import windows_validation
import test_forge
import hyperv_test_runner
import linux_test_runner


router = APIRouter(prefix="/api/coding", tags=["coding"])


class RepositoryInspectRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1_000)
    focus_path: str | None = Field(default=None, max_length=500)


class CodingProjectCreateRequest(BaseModel):
    request: str = Field(min_length=3, max_length=20_000)
    repository_path: str = Field(default="", max_length=1_000)
    target_mode: Literal["auto", "windows", "linux", "both"] = "auto"
    target_platforms: list[Literal["windows", "linux"]] | None = Field(default=None, min_length=1, max_length=2)
    autonomy: Literal["supervised", "autonomous"] = "autonomous"
    max_duration_minutes: int = Field(default=120, ge=5, le=1_440)
    max_iterations: int = Field(default=12, ge=1, le=100)
    max_files_changed: int = Field(default=50, ge=1, le=1_000)
    max_consecutive_failures: int = Field(default=3, ge=1, le=10)
    create_worktree: bool = True
    start_auto: bool = True
    confirmed: bool = False


class WindowsValidationRequest(BaseModel):
    files: list[str] = Field(default_factory=list, max_length=5_000)
    request: str = Field(default="", max_length=20_000)


class HyperVRunnerConfigRequest(BaseModel):
    vm_name: str = Field(min_length=1, max_length=100)
    checkpoint_name: str = Field(min_length=1, max_length=100)
    guest_username: str = Field(min_length=1, max_length=100)
    guest_password: str = Field(min_length=1, max_length=16_384)
    confirmed: bool = False


class LinuxResultSessionRequest(BaseModel):
    action: Literal["open", "restore"]
    run_id: str = Field(default="", max_length=80)
    confirmed: bool = False


@router.get("/overview")
async def coding_overview():
    missions = coding_mission.list_missions(limit=1000)
    radar = engineering_radar.context(list(language_registry.PROFILES), max_chars=200_000)
    return {
        "projects": len(missions),
        "running": sum(item.get("status") == "running" for item in missions),
        "completed": sum(item.get("status") == "completed" for item in missions),
        "failed": sum(item.get("status") == "failed" for item in missions),
        "languages": language_registry.matrix(),
        "knowledge": {
            **{key: value for key, value in radar.items() if key != "context"},
            "evidence_integrity": engineering_radar.evidence_integrity(),
        },
        "windows_validation": windows_validation.route(["main.ps1", "main.Tests.ps1"]),
        "test_forge": {
            "docker": test_forge.docker_status(),
            "debian_online_image": test_forge.IMAGES["debian13"],
            "offline_first": True,
            "installer_online_integration_required": True,
            "debian_vm": linux_test_runner.status(),
        },
        "job_store": coding_jobs.store_status(),
    }


@router.get("/projects")
async def coding_projects(
    limit: int = Query(default=100, ge=1, le=1000),
    status: str | None = Query(default=None, max_length=30),
):
    return {"projects": coding_mission.list_missions(limit=limit, status=status)}


@router.get("/projects/{mission_id}")
async def coding_project_detail(mission_id: str):
    try:
        mission = coding_mission.get(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if mission is None:
        raise HTTPException(status_code=404, detail="Projet de code introuvable.")
    return {
        "project": mission,
        "manifest": coding_mission.latest_manifest(mission_id),
        "events": coding_mission.list_events(mission_id, limit=500),
        "evidence_integrity": coding_mission.evidence_integrity(mission_id),
        "workspace": coding_workspace.status(mission_id) if coding_workspace.get(mission_id) else None,
        "auto_job": coding_jobs.latest_for_mission(mission_id),
        "delivery_pack": coding_mission.read_delivery_pack(mission_id),
    }


@router.get("/projects/{mission_id}/integrity")
async def coding_project_integrity(mission_id: str):
    try:
        return coding_mission.evidence_integrity(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{mission_id}/events/stream")
async def coding_project_events_stream(
    mission_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
):
    if coding_mission.get(mission_id) is None:
        raise HTTPException(status_code=404, detail="Projet de code introuvable.")

    async def events():
        cursor = after
        idle_ticks = 0
        while not await request.is_disconnected():
            batch = coding_mission.stream_events(mission_id, after=cursor, limit=200)
            for event in batch["events"]:
                cursor = int(event["cursor"])
                yield f"id: {cursor}\nevent: mission\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                idle_ticks = 0
            mission = batch.get("mission") or {}
            job = coding_jobs.latest_for_mission(mission_id) or {}
            terminal_status = (
                job.get("status")
                if job.get("status") in {"completed", "failed", "blocked", "cancelled"}
                else mission.get("status")
            )
            if terminal_status in {"completed", "failed", "blocked", "cancelled"} and not batch["events"]:
                yield f"event: terminal\ndata: {json.dumps({'cursor': cursor, 'status': terminal_status})}\n\n"
                return
            idle_ticks += 1
            if idle_ticks >= 20:
                yield f": heartbeat {cursor}\n\n"
                idle_ticks = 0
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })


@router.get("/projects/{mission_id}/file")
async def coding_project_file(
    mission_id: str,
    path: str = Query(min_length=1, max_length=500),
):
    try:
        files = coding_mission.latest_files(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if coding_mission.get(mission_id) is None:
        raise HTTPException(status_code=404, detail="Projet de code introuvable.")
    if path not in files:
        raise HTTPException(status_code=404, detail="Fichier absent du dernier snapshot.")
    return {"path": path, "content": files[path], "revision": coding_mission.get(mission_id)["revision"]}


@router.post("/repository/inspect")
async def coding_repository_inspect(payload: RepositoryInspectRequest):
    try:
        return repository_intelligence.inspect(payload.path, focus_path=payload.focus_path)
    except (OSError, ValueError, repository_intelligence.RepositoryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/validation/windows/route")
async def coding_windows_validation_route(payload: WindowsValidationRequest):
    return windows_validation.route(payload.files, payload.request)


@router.get("/validation/windows/hyperv")
async def coding_windows_hyperv_status():
    return hyperv_test_runner.status()


@router.post("/validation/windows/hyperv/configure")
async def coding_windows_hyperv_configure(payload: HyperVRunnerConfigRequest):
    try:
        return hyperv_test_runner.configure(
            vm_name=payload.vm_name, checkpoint_name=payload.checkpoint_name,
            guest_username=payload.guest_username, guest_password=payload.guest_password,
            confirmed=payload.confirmed,
        )
    except (ValueError, hyperv_test_runner.HyperVRunnerError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/validation/linux/hyperv")
async def coding_linux_hyperv_status():
    return linux_test_runner.status()


@router.post("/validation/linux/hyperv/session")
async def coding_linux_hyperv_session(payload: LinuxResultSessionRequest):
    try:
        if payload.action == "open":
            return linux_test_runner.open_result(run_id=payload.run_id, confirmed=payload.confirmed)
        return linux_test_runner.restore_clean(confirmed=payload.confirmed)
    except (OSError, ValueError, linux_test_runner.LinuxRunnerError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/projects", status_code=201)
async def coding_project_create(payload: CodingProjectCreateRequest):
    if payload.create_worktree and not payload.confirmed:
        raise HTTPException(status_code=409, detail="Confirme explicitement la création du worktree isolé.")
    try:
        return coding_service.start(
            payload.request,
            repository_path=payload.repository_path,
            target_mode=payload.target_mode,
            target_platforms=payload.target_platforms,
            autonomy=payload.autonomy,
            max_duration_minutes=payload.max_duration_minutes,
            max_iterations=payload.max_iterations,
            max_files_changed=payload.max_files_changed,
            max_consecutive_failures=payload.max_consecutive_failures,
            create_worktree=payload.create_worktree,
            start_auto=payload.start_auto,
            confirmed=payload.confirmed,
        )
    except coding_service.CodingServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/projects/{mission_id}/workspace")
async def coding_project_workspace(mission_id: str):
    if coding_mission.get(mission_id) is None:
        raise HTTPException(status_code=404, detail="Projet de code introuvable.")
    try:
        return coding_workspace.status(mission_id)
    except coding_workspace.WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{mission_id}/diff")
async def coding_project_diff(mission_id: str):
    if coding_mission.get(mission_id) is None:
        raise HTTPException(status_code=404, detail="Projet de code introuvable.")
    try:
        return coding_workspace.diff(mission_id)
    except coding_workspace.WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs")
async def coding_auto_jobs(
    mission_id: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
):
    return {"jobs": coding_jobs.list_jobs(mission_id=mission_id, limit=limit)}


@router.get("/jobs/{job_id}")
async def coding_auto_job(job_id: str):
    job = coding_jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job Auto introuvable.")
    return job


@router.post("/jobs/{job_id}/cancel")
async def coding_auto_job_cancel(job_id: str):
    job = coding_jobs.cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job Auto introuvable.")
    return job


@router.post("/jobs/{job_id}/resume")
async def coding_auto_job_resume(job_id: str):
    job = coding_jobs.resume_job(job_id)
    if not job:
        raise HTTPException(status_code=409, detail="Ce job ne peut pas être repris.")
    return job
