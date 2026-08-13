"""Domaine des outils Tâches et Notes de Marvin."""

from __future__ import annotations

from typing import Any

import database as db
import note_lifecycle


def parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(tag).strip() for tag in raw if str(tag).strip()]
    if isinstance(raw, str) and raw.strip():
        return [tag.strip() for tag in raw.split(",") if tag.strip()]
    return []


async def task_create(args: dict[str, Any]) -> dict[str, Any]:
    try:
        task = db.create_task(
            title=args["title"],
            description=args.get("description", ""),
            priority=args.get("priority", "medium"),
            due_date=args.get("due_date"),
            tags=parse_tags(args.get("tags", [])),
        )
        return {"success": True, "message": f"Tâche créée : « {task['title']} »", "task": task}
    except Exception as exc:
        return {"error": str(exc)}


async def task_list(args: dict[str, Any]) -> dict[str, Any]:
    try:
        status = args.get("status") or None
        if status == "all":
            status = None
        tasks = db.list_tasks(status=status, priority=args.get("priority"))
        return {"success": True, "count": len(tasks), "tasks": tasks}
    except Exception as exc:
        return {"error": str(exc)}


_STATUS_ALIASES = {
    "completed": "done", "terminé": "done", "termine": "done", "fini": "done",
    "wip": "in_progress", "en cours": "in_progress", "started": "in_progress",
    "todo": "pending", "à faire": "pending", "a faire": "pending",
    "annulé": "cancelled", "annule": "cancelled", "canceled": "cancelled",
}


async def task_update(args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("id") or "")
    if not task_id:
        return {"error": "ID de tâche requis"}
    update_args = dict(args)
    if "status" in update_args:
        status = update_args["status"]
        if not isinstance(status, str):
            return {"error": "Statut de tâche invalide : texte attendu"}
        normalized = status.lower().strip()
        update_args["status"] = _STATUS_ALIASES.get(normalized, status)
    try:
        task = db.update_task(task_id, update_args)
        if not task:
            return {"error": f"Tâche introuvable : {task_id}"}
        return {"success": True, "message": "Tâche mise à jour", "task": task}
    except Exception as exc:
        return {"error": str(exc)}


async def task_delete(args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("id") or "")
    if not task_id:
        return {"error": "ID de tâche requis"}
    if not args.get("confirmed"):
        try:
            preview = db.get_task(task_id)
            label = f"« {preview['title']} »" if preview else f"ID {task_id}"
        except Exception:
            label = f"ID {task_id}"
        return {"requiresConfirmation": True, "message": f"Supprimer définitivement la tâche {label} ?"}
    try:
        task = db.get_task(task_id)
        if not task:
            return {"error": f"Tâche introuvable : {task_id}"}
        db.delete_task(task_id)
        return {"success": True, "message": f"Tâche « {task['title']} » supprimée"}
    except Exception as exc:
        return {"error": str(exc)}


async def note_create(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await note_lifecycle.create(
            title=args["title"],
            content=args.get("content", ""),
            tags=parse_tags(args.get("tags", [])),
            pinned=args.get("pinned", False),
        )
        note = result["note"]
        if result["consistency"] == "degraded":
            return {
                **result,
                "message": (
                    f"Note « {note['title']} » enregistrée, mais sa recherche sémantique "
                    "doit être réparée."
                ),
            }
        return {**result, "message": f"Note créée : « {note['title']} »"}
    except Exception as exc:
        return {"error": str(exc)}


async def note_list(args: dict[str, Any]) -> dict[str, Any]:
    try:
        search = args.get("search") or args.get("tag") or None
        notes = db.list_notes(search=search, pinned=args.get("pinned"))
        return {"success": True, "count": len(notes), "notes": notes}
    except Exception as exc:
        return {"error": str(exc)}


async def note_update(args: dict[str, Any]) -> dict[str, Any]:
    note_id = str(args.get("id") or "")
    if not note_id:
        return {"error": "ID de note requis"}
    try:
        update_args = dict(args)
        if "tags" in update_args:
            update_args["tags"] = parse_tags(update_args["tags"])
        result = await note_lifecycle.update(note_id, update_args)
        if result.get("error") == "not_found":
            return {"error": f"Note introuvable : {note_id}"}
        if result["consistency"] == "degraded":
            return {
                **result,
                "message": "Note mise à jour; recherche sémantique à réparer.",
            }
        return {**result, "message": "Note mise à jour"}
    except Exception as exc:
        return {"error": str(exc)}


async def note_delete(args: dict[str, Any]) -> dict[str, Any]:
    note_id = str(args.get("id") or "")
    if not note_id:
        return {"error": "ID de note requis"}
    if not args.get("confirmed"):
        try:
            preview = db.get_note(note_id)
            label = f"« {preview['title']} »" if preview else f"ID {note_id}"
        except Exception:
            label = f"ID {note_id}"
        return {"requiresConfirmation": True, "message": f"Supprimer définitivement la note {label} ?"}
    try:
        note = db.get_note(note_id)
        if not note:
            return {"error": f"Note introuvable : {note_id}"}
        result = await note_lifecycle.delete(note_id)
        if not result.get("success"):
            return {
                "error": "La suppression n'est pas complète; la note reste autoritative.",
                **result,
            }
        return {**result, "message": f"Note « {note['title']} » supprimée"}
    except Exception as exc:
        return {"error": str(exc)}
