"""Orchestration durable et compensable des tâches longues."""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class DatabaseFacade(Protocol):
    def create_task(self, **kwargs: Any) -> dict[str, Any]: ...
    def delete_task(self, task_id: str) -> None: ...
    def list_tasks(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def create_cron_job(self, **kwargs: Any) -> dict[str, Any]: ...
    def list_cron_jobs(self) -> list[dict[str, Any]]: ...
    def update_cron_job(
        self, job_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None: ...


class MissionFacade(Protocol):
    def create_mission(self, **kwargs: Any) -> dict[str, Any]: ...
    def find_active(self, **kwargs: Any) -> dict[str, Any] | None: ...
    def sync_steps(
        self, mission_id: str, steps: list[dict[str, Any]]
    ) -> dict[str, Any]: ...
    def stop_mission(self, mission_id: str, reason: str) -> dict[str, Any]: ...


_database: DatabaseFacade | None = None
_missions: MissionFacade | None = None
_generate: Callable[..., Awaitable[str | None]] | None = None
_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:8]
_MAX_GOAL_LENGTH = 4_000
_MAX_STEPS = 8
_MAX_STEP_LENGTH = 1_000


def configure(
    *,
    database: DatabaseFacade,
    missions: MissionFacade,
    generate: Callable[..., Awaitable[str | None]],
    id_factory: Callable[[], str] | None = None,
) -> None:
    global _database, _missions, _generate, _id_factory
    _database = database
    _missions = missions
    _generate = generate
    _id_factory = id_factory or (lambda: uuid.uuid4().hex[:8])


def _dependencies() -> tuple[
    DatabaseFacade,
    MissionFacade,
    Callable[..., Awaitable[str | None]],
]:
    if _database is None or _missions is None or _generate is None:
        raise RuntimeError("Le domaine des tâches longues n'est pas configuré.")
    return _database, _missions, _generate


def _validated_goal(args: dict[str, Any]) -> str:
    goal = args.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Paramètre 'goal' requis.")
    goal = goal.strip()
    if len(goal) > _MAX_GOAL_LENGTH:
        raise ValueError(f"'goal' est limité à {_MAX_GOAL_LENGTH} caractères.")
    return goal


def _validated_steps(raw_steps: Any) -> list[str]:
    if raw_steps is None:
        return []
    if not isinstance(raw_steps, list):
        raise ValueError("'steps' doit être une liste.")
    steps: list[str] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, str) or not raw_step.strip():
            raise ValueError("Chaque étape doit être une chaîne non vide.")
        step = raw_step.strip()
        if len(step) > _MAX_STEP_LENGTH:
            raise ValueError(
                f"Chaque étape est limitée à {_MAX_STEP_LENGTH} caractères."
            )
        steps.append(step)
    if len(steps) > _MAX_STEPS:
        raise ValueError(f"'steps' est limité à {_MAX_STEPS} éléments.")
    return steps


def _steps_from_model(raw: str) -> list[str]:
    steps = [
        line.lstrip("-•* ").strip()
        for line in raw.splitlines()
        if line.strip() and line.lstrip().startswith(("-", "•", "*"))
    ]
    return [step[:_MAX_STEP_LENGTH] for step in steps[:_MAX_STEPS] if step]


def _rollback_created_tasks(
    database: DatabaseFacade, task_ids: list[str]
) -> list[str]:
    failures: list[str] = []
    for task_id in reversed(task_ids):
        try:
            database.delete_task(task_id)
        except Exception as exc:  # compensation best effort, erreur rendue visible
            failures.append(f"{task_id}: {str(exc)[:120]}")
    return failures


async def start(args: dict[str, Any]) -> dict[str, Any]:
    """Propose puis démarre une mission longue avec compensation des écritures partielles."""
    database, missions, generate = _dependencies()
    try:
        goal = _validated_goal(args)
        steps = _validated_steps(args.get("steps"))
    except (TypeError, ValueError) as exc:
        return {"error": str(exc)}

    conversation_id = args.get("_conversation_id")
    if not isinstance(conversation_id, (str, int)) or not str(
        conversation_id
    ).strip():
        return {
            "error": "Cette tâche longue doit être démarrée depuis une conversation active."
        }

    if not (args.get("confirmed") and steps):
        prompt = (
            f"Objectif : {goal}\n\n"
            "Décompose en 2 à 8 ÉTAPES concrètes, dans l'ordre logique. IMPORTANT : ces "
            "étapes seront exécutées PAR UN ASSISTANT IA AUTONOME disposant d'outils "
            "(fichiers, commandes système, SSH, web, documents...) — PAS par un humain. "
            "Formule chaque étape comme une action que l'IA peut accomplir elle-même. "
            "Réponds UNIQUEMENT par une liste à puces, une étape par ligne."
        )
        try:
            raw = (await generate(prompt, model=args.get("model"), timeout=90)) or ""
        except Exception:
            raw = ""
        steps = _steps_from_model(raw)
        if not steps:
            return {
                "error": (
                    "Impossible de décomposer cet objectif en étapes claires — "
                    "reformule plus précisément."
                )
            }

    if not args.get("confirmed"):
        plan_text = "\n".join(
            f"{index + 1}. {step}" for index, step in enumerate(steps)
        )
        return {
            "requiresConfirmation": True,
            "goal": goal,
            "steps": steps,
            "message": (
                f"Plan proposé pour « {goal} » ({len(steps)} étape(s)) :\n"
                f"{plan_text}\n\nConfirme pour démarrer la tâche longue avec les "
                "mêmes étapes, ou reformule l'objectif."
            ),
        }

    base_slug = re.sub(r"[^a-z0-9]+", "-", goal.lower())[:31].strip("-") or "mission"
    slug = f"{base_slug}-{_id_factory()}"
    tag = f"longtask:{slug}"
    created_tasks: list[dict[str, Any]] = []
    try:
        for step in steps:
            created_tasks.append(
                database.create_task(
                    title=step,
                    description=f"Étape de la tâche longue : {goal}",
                    tags=[tag],
                )
            )
        database.create_cron_job(
            name=f"Reprise tâche longue : {goal[:60]}",
            tool_name="_long_task_resume",
            args={
                "conversation_id": str(conversation_id),
                "slug": slug,
                "goal": goal,
            },
            schedule="every 5 minutes",
        )
    except Exception as exc:
        task_ids = [
            str(task["id"]) for task in created_tasks if task.get("id") is not None
        ]
        rollback_failures = _rollback_created_tasks(database, task_ids)
        return {
            "error": f"Création de la tâche longue annulée : {str(exc)[:150]}",
            "rollback_complete": not rollback_failures,
            "rollback_failures": rollback_failures,
        }

    task_ids = [str(task["id"]) for task in created_tasks]
    mission = None
    mission_warning = None
    try:
        mission = missions.create_mission(
            goal=goal,
            conversation_id=str(conversation_id),
            tag=tag,
            steps=steps,
            task_ids=task_ids,
        )
    except Exception as exc:
        mission_warning = (
            "Mission OS indisponible; la checklist et la reprise planifiée restent actives : "
            f"{str(exc)[:120]}"
        )

    result: dict[str, Any] = {
        "success": True,
        "goal": goal,
        "steps": steps,
        "tag": tag,
        "task_ids": task_ids,
        "mission_id": mission.get("id") if mission else None,
        "rollback": {
            "available": True,
            "action": "long_task_stop",
            "tag": tag,
            "scope": "arrête la reprise; la checklist reste consultable",
        },
        "message": (
            f"{len(steps)} étape(s) créée(s) (tag « {tag} »). Continue maintenant "
            "sur la première étape; la reprise automatique prendra le relais."
        ),
    }
    if mission_warning:
        result["warning"] = mission_warning
    return result


async def status(args: dict[str, Any]) -> dict[str, Any]:
    """Retourne un état borné et synchronise Mission OS sans masquer ses erreurs."""
    database, missions, _generate_fn = _dependencies()
    raw_tag = args.get("tag", "")
    if not isinstance(raw_tag, str):
        return {"error": "'tag' doit être une chaîne."}
    tag = raw_tag.strip()
    all_tasks = database.list_tasks(limit=200)
    relevant = [
        task
        for task in all_tasks
        if any(
            isinstance(item, str) and item.startswith("longtask:")
            for item in (task.get("tags") or [])
        )
        and (not tag or tag in (task.get("tags") or []))
    ]
    if not relevant:
        return {"success": True, "count": 0, "message": "Aucune tâche longue en cours."}

    by_tag: dict[str, list[dict[str, Any]]] = {}
    for task in relevant:
        for task_tag in task.get("tags") or []:
            if isinstance(task_tag, str) and task_tag.startswith("longtask:"):
                by_tag.setdefault(task_tag, []).append(task)
    groups = [
        {
            "tag": task_tag,
            "total": len(tasks),
            "done": sum(1 for task in tasks if task.get("status") == "done"),
            "steps": [
                {
                    "id": task["id"],
                    "title": task["title"],
                    "status": task["status"],
                }
                for task in tasks
            ],
        }
        for task_tag, tasks in by_tag.items()
    ]
    sync_errors: list[str] = []
    for group in groups:
        try:
            mission = missions.find_active(tag=group["tag"])
            if mission:
                missions.sync_steps(
                    mission["id"],
                    [
                        {"id": step["id"], "status": step["status"]}
                        for step in group["steps"]
                    ],
                )
                group["mission_id"] = mission["id"]
        except Exception as exc:
            sync_errors.append(f"{group['tag']}: {str(exc)[:120]}")
    result = {
        "success": True,
        "groups": groups,
        "message": f"{len(groups)} tâche(s) longue(s) trouvée(s).",
    }
    if sync_errors:
        result["sync_errors"] = sync_errors
    return result


async def stop(args: dict[str, Any]) -> dict[str, Any]:
    """Désactive les reprises d'une mission sans supprimer sa checklist."""
    database, missions, _generate_fn = _dependencies()
    raw_tag = args.get("tag")
    if not isinstance(raw_tag, str):
        return {"error": "Paramètre 'tag' requis (voir long_task_status pour la liste)."}
    tag = raw_tag.strip()
    slug = tag.split(":", 1)[-1] if ":" in tag else tag
    if not slug or not re.fullmatch(r"[a-z0-9-]{1,80}", slug):
        return {"error": "Tag de tâche longue invalide."}

    stopped = 0
    for job in database.list_cron_jobs():
        if (
            job.get("tool_name") == "_long_task_resume"
            and (job.get("args") or {}).get("slug") == slug
        ):
            database.update_cron_job(str(job["id"]), {"enabled": False})
            stopped += 1

    mission_warning = None
    try:
        mission = missions.find_active(tag=f"longtask:{slug}")
        if mission:
            missions.stop_mission(
                mission["id"], "reprise automatique arrêtée"
            )
    except Exception as exc:
        mission_warning = f"État Mission OS non synchronisé : {str(exc)[:120]}"
    result = {
        "success": True,
        "stopped": stopped,
        "message": (
            f"{stopped} reprise(s) automatique(s) arrêtée(s)."
            if stopped
            else "Aucune reprise automatique trouvée pour ce tag."
        ),
    }
    if mission_warning:
        result["warning"] = mission_warning
    return result
