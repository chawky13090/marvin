"""Organisation métier des projets et conversations depuis les outils Marvin.

Le module ne dépend ni de FastAPI ni du frontend. Les mutations passent par les
repositories existants et retournent un manifeste de compensation exploitable.
"""

from __future__ import annotations

from typing import Any

import database as db


MAX_NAME_LENGTH = 120
MAX_BULK_CONVERSATIONS = 50


def _clean_name(value: Any, *, label: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError(f"{label} requis.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"{label} limité à {MAX_NAME_LENGTH} caractères.")
    return name


def _public_project(project: dict | None) -> dict | None:
    if not project:
        return None
    return {
        "id": project.get("id"),
        "name": project.get("name"),
        "instructions": project.get("instructions") or "",
        "created_at": project.get("created_at"),
        "updated_at": project.get("updated_at"),
    }


def _public_conversation(conversation: dict | None) -> dict | None:
    if not conversation:
        return None
    return {
        "id": conversation.get("id"),
        "title": conversation.get("title"),
        "project_id": conversation.get("project_id"),
        "pinned": bool(conversation.get("pinned")),
        "archived": bool(conversation.get("archived_at")),
        "updated_at": conversation.get("updated_at"),
    }


def _project_by_reference(args: dict, *, allow_none: bool = False) -> dict | None:
    project_id = str(args.get("project_id") or "").strip()
    project_name = str(args.get("project_name") or "").strip()
    if allow_none and (
        args.get("remove_from_project") is True
        or project_id.casefold() in {"none", "null", "aucun", "sans projet"}
        or project_name.casefold() in {"none", "null", "aucun", "sans projet"}
    ):
        return None
    if project_id:
        project = db.get_project(project_id)
        if not project:
            raise ValueError("Projet introuvable.")
        return project
    if not project_name:
        raise ValueError("Indiquez project_id ou project_name.")
    matches = [
        project
        for project in db.get_projects()
        if str(project.get("name") or "").strip().casefold() == project_name.casefold()
    ]
    if not matches:
        raise ValueError(f"Projet « {project_name} » introuvable.")
    if len(matches) > 1:
        raise ValueError(
            f"Plusieurs projets portent le nom « {project_name} » ; utilisez project_id."
        )
    return matches[0]


def _conversation_by_reference(args: dict) -> dict:
    conversation_id = str(
        args.get("conversation_id") or args.get("_conversation_id") or ""
    ).strip()
    title = str(args.get("title") or args.get("conversation_title") or "").strip()
    if conversation_id:
        conversation = db.get_conversation(conversation_id)
        if not conversation:
            raise ValueError("Conversation introuvable.")
        return conversation
    if not title:
        raise ValueError(
            "Indiquez conversation_id, conversation_title, ou utilisez la conversation courante."
        )
    matches = [
        conversation
        for conversation in db.search_conversations(title, 20)
        if str(conversation.get("title") or "").strip().casefold() == title.casefold()
    ]
    if not matches:
        raise ValueError(f"Conversation « {title} » introuvable.")
    if len(matches) > 1:
        return {
            "_ambiguous": True,
            "_query": title,
            "_matches": [_public_conversation(item) for item in matches[:10]],
        }
    return matches[0]


def _failure(exc: Exception) -> dict:
    return {
        "success": False,
        "error": str(exc),
        "error_code": "WORKSPACE_ORGANIZATION_INVALID",
        "retryable": False,
    }


async def execute_project_list(args: dict) -> dict:
    projects = db.get_projects()
    conversations = db.list_conversations(1_000, 0, False)
    counts: dict[str, int] = {}
    for conversation in conversations:
        project_id = str(conversation.get("project_id") or "")
        if project_id:
            counts[project_id] = counts.get(project_id, 0) + 1
    return {
        "success": True,
        "summary": f"{len(projects)} projet(s).",
        "projects": [
            {**(_public_project(project) or {}), "conversation_count": counts.get(project["id"], 0)}
            for project in projects
        ],
    }


async def execute_project_create(args: dict) -> dict:
    try:
        name = _clean_name(args.get("name"), label="Nom du projet")
        existing = [
            project for project in db.get_projects()
            if str(project.get("name") or "").strip().casefold() == name.casefold()
        ]
        if existing:
            return {
                "success": True,
                "already_exists": True,
                "summary": f"Le projet « {existing[0]['name']} » existe déjà.",
                "project": _public_project(existing[0]),
                "ui_refresh": ["projects", "conversations"],
            }
        project = db.create_project(
            name,
            instructions=(str(args.get("instructions") or "").strip() or None),
        )
        return {
            "success": True,
            "summary": f"Projet « {project['name']} » créé dans la barre latérale.",
            "project": _public_project(project),
            "ui_refresh": ["projects", "conversations"],
            "rollback": {
                "tool": "project_delete",
                "arguments": {"project_id": project["id"]},
            },
        }
    except (ValueError, TypeError) as exc:
        return _failure(exc)


async def execute_project_update(args: dict) -> dict:
    try:
        project = _project_by_reference(args)
        new_name = args.get("new_name")
        instructions_supplied = "instructions" in args
        if new_name is None and not instructions_supplied:
            raise ValueError("Indiquez new_name et/ou instructions.")
        normalized_name = (
            _clean_name(new_name, label="Nouveau nom") if new_name is not None else None
        )
        if normalized_name:
            duplicate = [
                item for item in db.get_projects()
                if item.get("id") != project.get("id")
                and str(item.get("name") or "").strip().casefold()
                == normalized_name.casefold()
            ]
            if duplicate:
                raise ValueError(f"Le projet « {normalized_name} » existe déjà.")
        updated = db.update_project(
            project["id"],
            name=normalized_name,
            instructions=(
                str(args.get("instructions") or "")
                if instructions_supplied
                else None
            ),
        )
        return {
            "success": True,
            "summary": f"Projet « {updated['name']} » mis à jour.",
            "project": _public_project(updated),
            "ui_refresh": ["projects", "conversations"],
            "rollback": {
                "tool": "project_update",
                "arguments": {
                    "project_id": project["id"],
                    "new_name": project.get("name"),
                    "instructions": project.get("instructions") or "",
                },
            },
        }
    except (ValueError, TypeError) as exc:
        return _failure(exc)


async def execute_project_delete(args: dict) -> dict:
    try:
        if args.get("confirmed") is not True:
            return {
                "success": False,
                "requiresConfirmation": True,
                "summary": "La suppression du projet exige une confirmation dans l’interface.",
                "retryable": False,
            }
        project = _project_by_reference(args)
        affected = [
            _public_conversation(item)
            for item in db.list_conversations(1_000, 0, False)
            if item.get("project_id") == project["id"]
        ]
        db.delete_project(project["id"])
        return {
            "success": True,
            "summary": (
                f"Projet « {project['name']} » supprimé ; "
                f"{len(affected)} conversation(s) conservée(s) sans projet."
            ),
            "deleted_project": _public_project(project),
            "affected_conversations": affected,
            "ui_refresh": ["projects", "conversations"],
            "rollback_manifest": {
                "operation": "restore_project_and_assignments",
                "project": _public_project(project),
                "conversation_ids": [item["id"] for item in affected],
                "automatic": False,
            },
        }
    except (ValueError, TypeError) as exc:
        return _failure(exc)


async def execute_conversation_list(args: dict) -> dict:
    try:
        limit = max(1, min(int(args.get("limit") or 50), 200))
        archived = bool(args.get("archived", False))
        project = None
        if args.get("project_id") or args.get("project_name"):
            project = _project_by_reference(args)
        conversations = db.list_conversations(1_000, 0, archived)
        if project:
            conversations = [
                item for item in conversations if item.get("project_id") == project["id"]
            ]
        elif args.get("unassigned") is True:
            conversations = [item for item in conversations if not item.get("project_id")]
        return {
            "success": True,
            "summary": f"{min(len(conversations), limit)} conversation(s).",
            "conversations": [
                _public_conversation(item) for item in conversations[:limit]
            ],
        }
    except (ValueError, TypeError) as exc:
        return _failure(exc)


async def execute_conversation_search(args: dict) -> dict:
    try:
        query = _clean_name(args.get("query"), label="Recherche")
        limit = max(1, min(int(args.get("limit") or 20), 50))
        matches = db.search_conversations(query, limit)
        return {
            "success": True,
            "summary": f"{len(matches)} conversation(s) trouvée(s).",
            "conversations": [_public_conversation(item) for item in matches],
        }
    except (ValueError, TypeError) as exc:
        return _failure(exc)


async def execute_conversation_move(args: dict) -> dict:
    try:
        conversation = _conversation_by_reference(args)
        if conversation.get("_ambiguous"):
            return {
                "success": False,
                "requires_clarification": True,
                "error": (
                    f"Plusieurs conversations correspondent à « {conversation['_query']} »."
                ),
                "matches": conversation["_matches"],
                "retryable": False,
            }
        project = _project_by_reference(args, allow_none=True)
        old_project_id = conversation.get("project_id")
        new_project_id = project.get("id") if project else None
        db.update_conversation_project(conversation["id"], new_project_id)
        updated = db.get_conversation(conversation["id"])
        destination = f"le projet « {project['name']} »" if project else "Sans projet"
        return {
            "success": True,
            "summary": f"Conversation « {conversation['title']} » déplacée vers {destination}.",
            "conversation": _public_conversation(updated),
            "project": _public_project(project),
            "ui_refresh": ["projects", "conversations"],
            "rollback": {
                "tool": "conversation_move",
                "arguments": {
                    "conversation_id": conversation["id"],
                    "project_id": old_project_id or "none",
                    "remove_from_project": old_project_id is None,
                },
            },
        }
    except (ValueError, TypeError) as exc:
        return _failure(exc)


async def execute_conversation_move_many(args: dict) -> dict:
    try:
        raw_ids = args.get("conversation_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValueError("conversation_ids doit contenir au moins un identifiant.")
        conversation_ids = list(dict.fromkeys(str(item or "").strip() for item in raw_ids))
        if any(not item for item in conversation_ids):
            raise ValueError("Un identifiant de conversation est vide.")
        if len(conversation_ids) > MAX_BULK_CONVERSATIONS:
            raise ValueError(
                f"Maximum {MAX_BULK_CONVERSATIONS} conversations par déplacement."
            )
        conversations = []
        for conversation_id in conversation_ids:
            conversation = db.get_conversation(conversation_id)
            if not conversation:
                raise ValueError(f"Conversation introuvable : {conversation_id}.")
            conversations.append(conversation)
        project = _project_by_reference(args, allow_none=True)
        new_project_id = project.get("id") if project else None
        previous = {
            conversation["id"]: conversation.get("project_id")
            for conversation in conversations
        }
        moved: list[str] = []
        try:
            for conversation in conversations:
                db.update_conversation_project(conversation["id"], new_project_id)
                moved.append(conversation["id"])
        except Exception:
            for conversation_id in reversed(moved):
                db.update_conversation_project(
                    conversation_id,
                    previous[conversation_id],
                )
            raise
        destination = f"« {project['name']} »" if project else "Sans projet"
        return {
            "success": True,
            "summary": (
                f"{len(conversations)} conversation(s) déplacée(s) vers {destination}."
            ),
            "conversation_ids": conversation_ids,
            "project": _public_project(project),
            "ui_refresh": ["projects", "conversations"],
            "rollback_manifest": {
                "operation": "restore_conversation_projects",
                "assignments": previous,
                "automatic": False,
            },
        }
    except (ValueError, TypeError) as exc:
        return _failure(exc)


async def execute_conversation_update(args: dict) -> dict:
    try:
        conversation = _conversation_by_reference(args)
        if conversation.get("_ambiguous"):
            return {
                "success": False,
                "requires_clarification": True,
                "error": "Plusieurs conversations portent ce titre.",
                "matches": conversation["_matches"],
                "retryable": False,
            }
        previous = _public_conversation(conversation)
        action = str(args.get("action") or "").strip().casefold()
        if action == "rename":
            new_title = _clean_name(args.get("new_title"), label="Nouveau titre")
            db.update_conversation_title(conversation["id"], new_title)
        elif action in {"pin", "unpin"}:
            db.set_conversation_pinned(conversation["id"], action == "pin")
        elif action in {"archive", "restore"}:
            db.set_conversation_archived(conversation["id"], action == "archive")
        else:
            raise ValueError("Action attendue : rename, pin, unpin, archive ou restore.")
        updated = db.get_conversation(conversation["id"])
        inverse = {
            "rename": ("rename", previous["title"]),
            "pin": ("unpin", None),
            "unpin": ("pin", None),
            "archive": ("restore", None),
            "restore": ("archive", None),
        }[action]
        rollback_args = {
            "conversation_id": conversation["id"],
            "action": inverse[0],
        }
        if inverse[1] is not None:
            rollback_args["new_title"] = inverse[1]
        return {
            "success": True,
            "summary": f"Conversation « {updated['title']} » mise à jour ({action}).",
            "conversation": _public_conversation(updated),
            "ui_refresh": ["projects", "conversations"],
            "rollback": {
                "tool": "conversation_update",
                "arguments": rollback_args,
            },
        }
    except (ValueError, TypeError) as exc:
        return _failure(exc)
