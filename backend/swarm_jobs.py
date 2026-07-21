"""Jobs persistants et annulables pour Research Swarm."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import research_swarm
from config import DATA_DIR


JOBS_PATH = Path(DATA_DIR) / "research_swarm_jobs.json"
_LOCK = threading.RLock()
_TASKS: dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict[str, Any]]:
    try:
        value = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _write(rows: list[dict[str, Any]]) -> None:
    JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = JOBS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, JOBS_PATH)


def _update(job_id: str, **updates) -> dict[str, Any] | None:
    with _LOCK:
        rows = _load()
        for index, row in enumerate(rows):
            if row.get("id") == job_id:
                row = {**row, **updates, "updated_at": _now()}
                rows[index] = row
                _write(rows)
                return row
    return None


def recover_interrupted() -> None:
    with _LOCK:
        rows = _load()
        changed = False
        for row in rows:
            if row.get("status") in {"queued", "running"}:
                row["status"] = "interrupted"
                row["error"] = "Backend redémarré pendant l'exécution ; reprise disponible."
                row["updated_at"] = _now()
                changed = True
        if changed:
            _write(rows)


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    rows = _load()
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return rows[:max(1, min(int(limit), 500))]


def get_job(job_id: str) -> dict[str, Any] | None:
    return next((row for row in list_jobs(500) if row.get("id") == job_id), None)


async def _run(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    _update(job_id, status="running", progress={"stage": "starting", "completed": 0, "total": job["agent_count"]})
    async def progress(value):
        _update(job_id, progress=value)
    try:
        result = await research_swarm.execute(
            job["question"], agent_count=job["agent_count"],
            sources_per_agent=job["sources_per_agent"],
            max_duration_seconds=job["max_duration_seconds"],
            progress=progress,
            cancelled=lambda: bool(get_job(job_id).get("cancel_requested")),
        )
        if result.get("error"):
            _update(job_id, status="failed", error=result["error"], result=result)
        else:
            _update(job_id, status="completed", result=result, error=None)
    except asyncio.CancelledError:
        _update(job_id, status="cancelled", error="Annulation demandée.")
    except Exception as exc:
        _update(job_id, status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        _TASKS.pop(job_id, None)


def create_job(question: str, agent_count: int, sources_per_agent: int, max_duration_seconds: int) -> dict[str, Any]:
    job = {
        "id": "swarm-job-" + uuid.uuid4().hex[:12],
        "question": question,
        "agent_count": agent_count,
        "sources_per_agent": sources_per_agent,
        "max_duration_seconds": max_duration_seconds,
        "status": "queued",
        "progress": {"stage": "queued", "completed": 0, "total": agent_count},
        "cancel_requested": False,
        "result": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _LOCK:
        rows = _load()
        rows.append(job)
        _write(rows[-200:])
    _TASKS[job["id"]] = asyncio.create_task(_run(job["id"]))
    return job


def cancel_job(job_id: str) -> dict[str, Any] | None:
    job = _update(job_id, cancel_requested=True)
    task = _TASKS.get(job_id)
    if task and not task.done():
        task.cancel()
    return job


def resume_job(job_id: str) -> dict[str, Any] | None:
    old = get_job(job_id)
    if not old or old.get("status") not in {"interrupted", "failed", "cancelled"}:
        return None
    return create_job(
        old["question"], old["agent_count"], old["sources_per_agent"], old["max_duration_seconds"],
    )


recover_interrupted()
