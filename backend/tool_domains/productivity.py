"""Domaine des outils Tâches et Notes de Marvin."""

from __future__ import annotations

from typing import Any

import database as db


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


async def _index_note(note: dict[str, Any]) -> None:
    try:
        from vector_store import index_note

        await index_note(note["id"], note["title"], note["content"], note.get("tags", []))
    except Exception:
        pass


async def _delete_note_index(note_id: str) -> None:
    try:
        from vector_store import delete_document

        await delete_document("notes", note_id)
    except Exception:
        pass


async def note_create(args: dict[str, Any]) -> dict[str, Any]:
    try:
        note = db.create_note(
            title=args["title"],
            content=args.get("content", ""),
            tags=parse_tags(args.get("tags", [])),
            pinned=args.get("pinned", False),
        )
        await _index_note(note)
        return {"success": True, "message": f"Note créée : « {note['title']} »", "note": note}
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
        note = db.update_note(note_id, update_args)
        if not note:
            return {"error": f"Note introuvable : {note_id}"}
        await _index_note(note)
        return {"success": True, "message": "Note mise à jour", "note": note}
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
        db.delete_note(note_id)
        await _delete_note_index(note_id)
        return {"success": True, "message": f"Note « {note['title']} » supprimée"}
    except Exception as exc:
        return {"error": str(exc)}
