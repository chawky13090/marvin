"""Cohérence explicite des notes entre SQLite et l'index Qdrant dérivé."""

from __future__ import annotations

import asyncio
from typing import Any

import database as db


_MUTATION_LOCK = asyncio.Lock()


async def _index(note: dict[str, Any]) -> None:
    from vector_store import index_note

    indexed = await index_note(
        str(note["id"]),
        str(note["title"]),
        str(note.get("content") or ""),
        list(note.get("tags") or []),
    )
    if indexed is not True:
        raise RuntimeError("Index de notes indisponible.")


async def _delete_index(note_id: str) -> None:
    from vector_store import delete_document

    deleted = await delete_document("notes", str(note_id))
    if deleted is not True:
        raise RuntimeError("Index de notes indisponible.")


def _degraded(note: dict[str, Any], stage: str, exc: Exception) -> dict[str, Any]:
    return {
        "success": True,
        "note": note,
        "consistency": "degraded",
        "warnings": [f"{stage}:{type(exc).__name__}"],
        "message": "Note enregistrée dans SQLite; indexation sémantique à réparer.",
    }


async def create(
    title: str,
    content: str = "",
    tags: list[str] | None = None,
    pinned: bool = False,
) -> dict[str, Any]:
    """SQLite reste autoritatif; une panne Qdrant est visible et réparable."""
    async with _MUTATION_LOCK:
        note = db.create_note(title=title, content=content, tags=tags or [], pinned=pinned)
        try:
            await _index(note)
        except Exception as exc:
            return _degraded(note, "qdrant_index", exc)
        return {
            "success": True,
            "note": note,
            "consistency": "complete",
            "warnings": [],
        }


async def update(note_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Applique la mise à jour autoritative puis qualifie sa projection."""
    async with _MUTATION_LOCK:
        note = db.update_note(str(note_id), updates)
        if note is None:
            return {"success": False, "error": "not_found", "stage": "sqlite"}
        try:
            await _index(note)
        except Exception as exc:
            return _degraded(note, "qdrant_index", exc)
        return {
            "success": True,
            "note": note,
            "consistency": "complete",
            "warnings": [],
        }


async def delete(note_id: str) -> dict[str, Any]:
    """Supprime l'index avant SQLite et compense si la source refuse l'effacement."""
    async with _MUTATION_LOCK:
        note = db.get_note(str(note_id))
        if note is None:
            return {"success": False, "deleted": False, "error": "not_found", "stage": "sqlite"}
        try:
            await _delete_index(str(note_id))
        except Exception as exc:
            return {
                "success": False,
                "deleted": False,
                "stage": "qdrant",
                "error_type": type(exc).__name__,
                "compensated": True,
            }
        try:
            db.delete_note(str(note_id))
        except Exception as exc:
            compensation_errors: list[str] = []
            try:
                restored = db.restore_note(note)
                await _index(restored)
            except Exception as compensation_exc:
                compensation_errors.append(type(compensation_exc).__name__)
            return {
                "success": False,
                "deleted": False,
                "stage": "sqlite",
                "error_type": type(exc).__name__,
                "compensated": not compensation_errors,
                "compensation_errors": compensation_errors,
            }
        return {
            "success": True,
            "deleted": True,
            "id": str(note_id),
            "title": str(note.get("title") or ""),
            "consistency": "complete",
        }
