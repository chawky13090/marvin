"""Cycle de vie cohérent des souvenirs entre SQLite, Memory Mesh et Qdrant."""

from __future__ import annotations

from typing import Any

import database as db
import memory_mesh


MEMORY_CATEGORIES = frozenset({"user_profile", "preference", "fact", "habit"})


def validate_category(category: str) -> str:
    normalized = str(category or "").strip()
    if normalized not in MEMORY_CATEGORIES:
        raise ValueError("Catégorie de souvenir non prise en charge.")
    return normalized


async def _delete_index(memory_id: str) -> None:
    from vector_store import delete_document

    await delete_document("memories", memory_id)


async def _index(memory_id: str, content: str, category: str) -> None:
    from vector_store import index_memory

    await index_memory(memory_id, content, category)


async def create(
    content: str,
    category: str = "fact",
    *,
    source: str = "user",
) -> dict[str, Any]:
    """Crée le souvenir autoritatif puis matérialise ses index, avec état explicite."""
    category = validate_category(category)
    memory = db.create_memory(content, category)
    errors: list[str] = []
    try:
        memory_mesh.register(
            memory["id"],
            memory["content"],
            memory["category"],
            source=source,
        )
    except Exception as exc:
        errors.append(f"mesh:{type(exc).__name__}")
    try:
        await _index(memory["id"], memory["content"], memory["category"])
    except Exception as exc:
        errors.append(f"index:{type(exc).__name__}")
    return {
        **memory,
        "consistency": "degraded" if errors else "complete",
        "warnings": errors,
    }


async def refresh(memory: dict[str, Any], *, source: str = "user") -> dict[str, Any]:
    """Régénère les projections d'un souvenir existant après mise à jour."""
    errors: list[str] = []
    try:
        memory_mesh.register(
            memory["id"],
            memory["content"],
            memory["category"],
            source=source,
        )
    except Exception as exc:
        errors.append(f"mesh:{type(exc).__name__}")
    try:
        await _index(memory["id"], memory["content"], memory["category"])
    except Exception as exc:
        errors.append(f"index:{type(exc).__name__}")
    return {
        "consistency": "degraded" if errors else "complete",
        "warnings": errors,
    }


async def forget(memory_id: str) -> dict[str, Any]:
    """Oublie d'abord les projections, puis la source SQLite autoritative.

    Si Qdrant ou le Mesh ne peuvent pas être nettoyés, SQLite reste intact et
    l'appelant reçoit un échec réessayable : aucun oubli partiel n'est présenté
    comme réussi.
    """
    try:
        await _delete_index(memory_id)
    except Exception as exc:
        return {
            "success": False,
            "forgotten": False,
            "stage": "index",
            "error_type": type(exc).__name__,
        }
    try:
        memory_mesh.remove(memory_id)
    except Exception as exc:
        return {
            "success": False,
            "forgotten": False,
            "stage": "mesh",
            "error_type": type(exc).__name__,
        }
    try:
        db.delete_memory(memory_id)
    except Exception as exc:
        return {
            "success": False,
            "forgotten": False,
            "stage": "database",
            "error_type": type(exc).__name__,
        }
    return {"success": True, "forgotten": True, "id": memory_id}


async def clear_all() -> dict[str, Any]:
    """Oublie chaque souvenir avec le même contrat et expose toute panne partielle."""
    memories = db.get_memories()
    forgotten: list[str] = []
    failures: list[dict[str, str]] = []
    for memory in memories:
        memory_id = str(memory["id"])
        result = await forget(memory_id)
        if result.get("forgotten") is True:
            forgotten.append(memory_id)
        else:
            failures.append({
                "id": memory_id,
                "stage": str(result.get("stage") or "unknown"),
                "error_type": str(result.get("error_type") or "unknown"),
            })
    return {
        "success": not failures,
        "forgotten_count": len(forgotten),
        "failure_count": len(failures),
        "failures": failures,
    }


async def prune_expired() -> dict[str, Any]:
    """Applique physiquement la rétention déclarée dans Memory Mesh."""
    expired = sorted(memory_mesh.expired_ids())
    forgotten: list[str] = []
    failures: list[dict[str, str]] = []
    for memory_id in expired:
        result = await forget(memory_id)
        if result.get("forgotten") is True:
            forgotten.append(memory_id)
        else:
            failures.append({
                "id": memory_id,
                "stage": str(result.get("stage") or "unknown"),
                "error_type": str(result.get("error_type") or "unknown"),
            })
    return {
        "success": not failures,
        "expired_count": len(expired),
        "forgotten_count": len(forgotten),
        "failures": failures,
    }
