"""Moteur d'execution planifiee et reprise des taches longues Marvin."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any

import database as db
import tools as tool_module
from agent import run_agent
from scheduling import next_run_datetime


async def drain_run_agent(message: str, conversation_id: str) -> None:
    async for _ in run_agent(
        [{"role": "user", "content": message}], conversation_id, None
    ):
        pass


async def long_task_resume_tick(job: dict[str, Any], now_string: str) -> None:
    arguments = job.get("args") or {}
    conversation_id = arguments.get("conversation_id")
    slug = arguments.get("slug")
    goal = arguments.get("goal", "")
    if not conversation_id or not slug:
        db.update_cron_job(
            job["id"],
            {
                "enabled": False,
                "last_run": now_string,
                "last_result": json.dumps({"error": "job long_task mal formé"})[:500],
            },
        )
        return

    tag = f"longtask:{slug}"
    pending = [
        task
        for task in db.list_tasks(limit=200)
        if task.get("status") != "done" and tag in (task.get("tags") or [])
    ]
    if not pending:
        db.update_cron_job(
            job["id"],
            {
                "enabled": False,
                "last_run": now_string,
                "last_result": json.dumps(
                    {"message": f"Tâche longue « {goal[:80]} » terminée."}
                )[:500],
            },
        )
        try:
            notifier = tool_module.TOOLS_REGISTRY.get("pc_notify")
            if notifier:
                await notifier(
                    {
                        "title": "Marvin — Tâche longue terminée",
                        "message": goal[:200] or "Toutes les étapes sont faites.",
                    }
                )
        except Exception:
            pass
        return

    next_step = pending[0]
    nudge = (
        f"[Reprise automatique de tâche longue « {goal} »] Étape à traiter maintenant : "
        f"« {next_step['title']} » (identifiant de tâche : {next_step['id']}). Avance "
        "dessus avec les outils appropriés à cette étape précise — reste sur une action "
        "CIBLÉE et RAPIDE, évite un scan récursif ou une opération lourde qui prendrait "
        "plusieurs minutes — puis mets à jour le statut de cette tâche à 'done' une fois "
        f"terminée. Il reste {len(pending)} étape(s) au total sur cette tâche longue."
    )
    try:
        await asyncio.wait_for(drain_run_agent(nudge, conversation_id), timeout=180)
        result = {"message": "Reprise exécutée."}
    except asyncio.TimeoutError:
        result = {
            "message": "Reprise interrompue après 3 min ; progression conservée, suite au prochain cycle."
        }
    except Exception as exc:
        result = {"error": str(exc)[:200]}

    still_pending = [
        task
        for task in db.list_tasks(limit=200)
        if task.get("status") != "done" and tag in (task.get("tags") or [])
    ]
    stall_count = int(arguments.get("_stall_count") or 0)
    stall_count = stall_count + 1 if len(still_pending) >= len(pending) else 0
    updated_arguments = {**arguments, "_stall_count": stall_count}
    if stall_count >= 3:
        db.update_cron_job(
            job["id"],
            {
                "enabled": False,
                "args": updated_arguments,
                "last_run": now_string,
                "last_result": json.dumps(
                    {"message": "Tâche longue mise en pause ; aucune progression après 3 reprises."}
                )[:500],
            },
        )
        try:
            notifier = tool_module.TOOLS_REGISTRY.get("pc_notify")
            if notifier:
                await notifier(
                    {
                        "title": "Marvin — Tâche longue en attente",
                        "message": (
                            f"« {goal[:120]} » ne progresse plus (probablement en attente d'une "
                            "confirmation) — reprise automatique mise en pause. Ouvre la "
                            "conversation pour valider l'étape bloquante, puis relance-la."
                        ),
                    }
                )
        except Exception:
            pass
        return

    db.update_cron_job(
        job["id"],
        {
            "args": updated_arguments,
            "last_run": now_string,
            "next_run": next_run_datetime(job["schedule"]),
            "last_result": json.dumps(result)[:500],
            "run_count": True,
        },
    )


async def cron_worker() -> None:
    while True:
        try:
            now_string = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for job in db.list_cron_jobs(enabled_only=True):
                next_run = job.get("next_run")
                if next_run and next_run > now_string:
                    continue
                if job["tool_name"] == "_long_task_resume":
                    await long_task_resume_tick(job, now_string)
                    continue
                executor = tool_module.TOOLS_REGISTRY.get(job["tool_name"])
                result: dict[str, Any] = {
                    "error": f"Outil '{job['tool_name']}' introuvable"
                }
                duration_ms = 0
                if executor:
                    started = time.monotonic()
                    try:
                        result = await executor(dict(job.get("args") or {}))
                    except Exception as exc:
                        result = {"error": str(exc)}
                    duration_ms = int((time.monotonic() - started) * 1000)
                    try:
                        db.log_execution(
                            job["tool_name"], job.get("args", {}), result, duration_ms
                        )
                    except Exception:
                        pass
                db.update_cron_job(
                    job["id"],
                    {
                        "last_run": now_string,
                        "next_run": next_run_datetime(job["schedule"]),
                        "last_result": json.dumps(result)[:500],
                        "run_count": True,
                    },
                )
        except Exception as exc:
            print(f"[CRON] Erreur worker: {exc}")
        await asyncio.sleep(30)
