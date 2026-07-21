"""Routes de planification Cron et monitoring système SSE."""

import asyncio
import json
from datetime import datetime, timedelta

import psutil
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import database as db
from scheduling import next_run_datetime, parse_schedule_seconds, to_cron


router = APIRouter(tags=["cron-monitor"])


class CronJobCreate(BaseModel):
    name: str
    tool_name: str
    args: dict = Field(default_factory=dict)
    schedule: str


class CronJobUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    args: dict | None = None
    enabled: bool | None = None


@router.get("/api/cron")
async def list_cron_jobs():
    return db.list_cron_jobs()


@router.post("/api/cron")
async def create_cron_job(body: CronJobCreate):
    job = db.create_cron_job(body.name, body.tool_name, body.args, body.schedule)
    db.update_cron_job(job["id"], {"next_run": next_run_datetime(body.schedule)})
    return db.get_cron_job(job["id"])


@router.put("/api/cron/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate):
    updates = body.model_dump(exclude_none=True)
    if updates.get("schedule"):
        updates["next_run"] = next_run_datetime(updates["schedule"])
    job = db.update_cron_job(job_id, updates)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job


@router.post("/api/cron/preview")
async def cron_preview(body: dict):
    schedule = body.get("schedule", "")
    now = datetime.now()
    cron = to_cron(schedule)
    runs = []
    if cron:
        try:
            from croniter import croniter

            iterator = croniter(cron, now)
            runs = [iterator.get_next(datetime).strftime("%a %d/%m %H:%M") for _ in range(5)]
        except Exception:
            pass
    if not runs:
        seconds = parse_schedule_seconds(schedule)
        runs = [
            (now + timedelta(seconds=seconds * (index + 1))).strftime("%a %d/%m %H:%M")
            for index in range(5)
        ]
    return {"schedule": schedule, "cron": cron, "next_runs": runs}


@router.delete("/api/cron/{job_id}")
async def delete_cron_job(job_id: str):
    db.delete_cron_job(job_id)
    return {"success": True}


def _monitor_payload() -> dict:
    memory = psutil.virtual_memory()
    disks = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append(
                {
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "total_gb": round(usage.total / 1024 ** 3, 1),
                    "used_gb": round(usage.used / 1024 ** 3, 1),
                    "free_gb": round(usage.free / 1024 ** 3, 1),
                    "percent": usage.percent,
                }
            )
        except Exception:
            pass
    network = psutil.net_io_counters()
    processes = []
    try:
        for process in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = process.info
                processes.append(
                    {
                        "pid": info["pid"],
                        "name": info["name"] or "?",
                        "cpu_percent": round(info["cpu_percent"] or 0.0, 1),
                        "memory_mb": round(
                            (info["memory_info"].rss if info["memory_info"] else 0) / 1024 ** 2,
                            1,
                        ),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        processes.sort(key=lambda item: item["cpu_percent"], reverse=True)
    except Exception:
        pass
    gpu = None
    try:
        import local_video

        info = local_video.get_device_info()
        gpu = {
            "name": info.get("device_name") or info.get("name"),
            "vram_gb": info.get("vram_gb"),
            "backend": info.get("backend"),
            "vendor": info.get("vendor"),
        }
    except Exception:
        pass
    payload = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(),
        "ram_total_gb": round(memory.total / 1024 ** 3, 1),
        "ram_used_gb": round(memory.used / 1024 ** 3, 1),
        "ram_percent": memory.percent,
        "disks": disks,
        "net_sent_mb": round(network.bytes_sent / 1024 ** 2, 1),
        "net_recv_mb": round(network.bytes_recv / 1024 ** 2, 1),
        "top_processes": processes[:8],
        "gpu": gpu,
    }
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            payload["battery"] = {
                "percent": round(battery.percent, 1),
                "plugged": battery.power_plugged,
            }
    except Exception:
        pass
    return payload


@router.get("/api/monitor")
async def monitor_stream():
    async def generate():
        while True:
            try:
                yield f"data: {json.dumps(_monitor_payload())}\n\n"
            except Exception as error:
                yield f"data: {json.dumps({'error': str(error)})}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
