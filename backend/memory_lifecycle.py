"""Cycle de vie cohérent des souvenirs entre SQLite, Memory Mesh et Qdrant."""

from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any

import database as db
import memory_mesh


MEMORY_CATEGORIES = frozenset({"user_profile", "preference", "fact", "habit"})


def _inspect_index(expected_hashes: dict[str, str]) -> dict[str, Any]:
    from vector_store import inspect_memory_index

    return inspect_memory_index(expected_hashes)


def validate_category(category: str) -> str:
    normalized = str(category or "").strip()
    if normalized not in MEMORY_CATEGORIES:
        raise ValueError("Catégorie de souvenir non prise en charge.")
    return normalized


async def _delete_index(memory_id: str) -> None:
    from vector_store import delete_document

    if await delete_document("memories", memory_id) is not True:
        raise RuntimeError("Index mémoire indisponible.")


async def _index(memory_id: str, content: str, category: str) -> None:
    from vector_store import index_memory

    if await index_memory(memory_id, content, category) is not True:
        raise RuntimeError("Index mémoire indisponible.")


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


async def confirm(memory_id: str, *, source: str = "user_confirmation") -> dict[str, Any]:
    """Revalide explicitement la fraîcheur d'un souvenir existant."""
    memory = next(
        (
            item for item in db.get_memories()
            if str(item.get("id") or "") == str(memory_id)
        ),
        None,
    )
    if memory is None:
        return {"success": False, "confirmed": False, "error": "not_found"}
    projection = await refresh(memory, source=source)
    return {
        "success": projection["consistency"] == "complete",
        "confirmed": projection["consistency"] == "complete",
        "id": str(memory_id),
        **projection,
    }


async def forget(memory_id: str) -> dict[str, Any]:
    """Oublie d'abord les projections, puis la source SQLite autoritative.

    Si Qdrant ou le Mesh ne peuvent pas être nettoyés, SQLite reste intact et
    l'appelant reçoit un échec réessayable : aucun oubli partiel n'est présenté
    comme réussi.
    """
    memory = next(
        (
            item for item in db.get_memories()
            if str(item.get("id") or "") == str(memory_id)
        ),
        None,
    )
    if memory is None:
        return {
            "success": False,
            "forgotten": False,
            "stage": "database",
            "error_type": "NotFound",
            "compensated": True,
        }
    try:
        await _delete_index(memory_id)
    except Exception as exc:
        return {
            "success": False,
            "forgotten": False,
            "stage": "index",
            "error_type": type(exc).__name__,
            "compensated": True,
        }
    try:
        memory_mesh.remove(memory_id)
    except Exception as exc:
        compensation = await refresh(memory, source="delete_compensation")
        return {
            "success": False,
            "forgotten": False,
            "stage": "mesh",
            "error_type": type(exc).__name__,
            "compensated": compensation["consistency"] == "complete",
            "compensation_warnings": compensation["warnings"],
        }
    try:
        db.delete_memory(memory_id)
    except Exception as exc:
        compensation = await refresh(memory, source="delete_compensation")
        return {
            "success": False,
            "forgotten": False,
            "stage": "database",
            "error_type": type(exc).__name__,
            "compensated": compensation["consistency"] == "complete",
            "compensation_warnings": compensation["warnings"],
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


def audit_consistency() -> dict[str, Any]:
    """Compare la source SQLite à Memory Mesh et au client Qdrant partagé."""
    memories = db.get_memories()
    by_id = {str(item["id"]): item for item in memories}
    metadata = {
        str(item.get("memory_id") or ""): item
        for item in memory_mesh.list_metadata()
        if str(item.get("memory_id") or "")
    }
    database_ids = set(by_id)
    mesh_ids = set(metadata)
    stale = sorted(
        memory_id
        for memory_id in database_ids & mesh_ids
        if metadata[memory_id].get("content_sha256")
        != memory_mesh.content_sha256(str(by_id[memory_id].get("content") or ""))
    )

    def valid_metadata(item: dict[str, Any]) -> bool:
        try:
            confidence = float(item.get("confidence"))
            datetime.fromisoformat(str(item.get("valid_from") or ""))
            if item.get("expires_at"):
                datetime.fromisoformat(str(item["expires_at"]))
            datetime.fromisoformat(str(item.get("review_after") or ""))
        except (TypeError, ValueError):
            return False
        return (
            item.get("kind") in {"working", "episodic", "semantic", "procedural"}
            and item.get("category") in MEMORY_CATEGORIES
            and bool(str(item.get("source") or "").strip())
            and math.isfinite(confidence)
            and 0.0 <= confidence <= 1.0
            and bool(re.fullmatch(r"[0-9a-f]{64}", str(item.get("content_sha256") or "")))
            and isinstance(item.get("source_history"), list)
            and isinstance(item.get("contradictions"), list)
        )

    invalid = sorted(
        memory_id
        for memory_id, item in metadata.items()
        if not valid_metadata(item)
    )
    index = _inspect_index({
        memory_id: memory_mesh.content_sha256(
            str(memory.get("content") or "")
        )
        for memory_id, memory in by_id.items()
    })
    index_issues = (
        not index["available"]
        or any(
            index[key]
            for key in ("missing", "orphan", "stale", "unprotected", "corrupt")
        )
    )
    return {
        "consistent": not (
            database_ids - mesh_ids
            or mesh_ids - database_ids
            or stale
            or invalid
            or index_issues
        ),
        "database_count": len(database_ids),
        "mesh_count": len(mesh_ids),
        "missing_mesh": sorted(database_ids - mesh_ids),
        "orphan_mesh": sorted(mesh_ids - database_ids),
        "stale_content": stale,
        "invalid_metadata": invalid,
        "expired": sorted(memory_mesh.expired_ids()),
        "conflicted": sorted(memory_mesh.conflicted_ids()),
        "stale_review": sorted(memory_mesh.stale_ids()),
        "index": index,
    }


async def repair_consistency(*, dry_run: bool = True) -> dict[str, Any]:
    """Répare uniquement les projections; SQLite reste la source autoritative."""
    before = audit_consistency()
    if dry_run:
        return {"success": True, "dry_run": True, "before": before, "actions": []}
    memories = {
        str(item["id"]): item
        for item in db.get_memories()
    }
    actions: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for memory_id in sorted(
        set(before["missing_mesh"])
        | set(before["stale_content"])
        | set(before["invalid_metadata"])
        | set(before["index"]["missing"])
        | set(before["index"]["stale"])
        | set(before["index"]["unprotected"])
        | set(before["index"]["corrupt"])
    ):
        memory = memories.get(memory_id)
        if not memory:
            continue
        projection = await refresh(memory, source="reconciliation")
        actions.append({"id": memory_id, "action": "refresh"})
        for warning in projection.get("warnings") or []:
            failures.append(
                {"id": memory_id, "stage": str(warning).split(":", 1)[0]}
            )
    for memory_id in before["orphan_mesh"]:
        try:
            await _delete_index(memory_id)
            memory_mesh.remove(memory_id)
            actions.append({"id": memory_id, "action": "remove_orphan"})
        except Exception as exc:
            failures.append(
                {
                    "id": memory_id,
                    "stage": "orphan",
                    "error_type": type(exc).__name__,
                }
            )
    for memory_id in before["index"]["orphan"]:
        try:
            await _delete_index(memory_id)
            actions.append({"id": memory_id, "action": "remove_index_orphan"})
        except Exception as exc:
            failures.append(
                {
                    "id": memory_id,
                    "stage": "index_orphan",
                    "error_type": type(exc).__name__,
                }
            )
    after = audit_consistency()
    return {
        "success": not failures and after["consistent"],
        "dry_run": False,
        "before": before,
        "after": after,
        "actions": actions,
        "failures": failures,
    }
