"""Domaine des outils de mémoire durable de Marvin."""

from __future__ import annotations

from typing import Any

import database as db


def _register_mesh(memory_id: str, content: str, category: str) -> None:
    try:
        import memory_mesh

        memory_mesh.register(memory_id, content, category)
    except Exception:
        pass


async def _index_memory(memory_id: str, content: str, category: str) -> None:
    try:
        from vector_store import index_memory

        await index_memory(memory_id, content, category)
    except Exception:
        pass


async def _delete_memory_index(memory_id: str) -> None:
    try:
        from vector_store import delete_document

        await delete_document("memories", memory_id)
    except Exception:
        pass


async def _semantic_search(query: str, limit: int) -> list[dict[str, Any]]:
    from vector_store import search as vector_search

    return await vector_search(query, collections=["memories"], limit=limit)


async def save(args: dict[str, Any]) -> dict[str, Any]:
    content = str(args.get("content") or "").strip()
    category = str(args.get("category") or "fact")
    if not content:
        return {"error": "Contenu requis"}
    try:
        try:
            existing = db.get_memories()
            content_norm = content.lower()
            for memory in existing:
                if memory.get("category") != category:
                    continue
                existing_content = str(memory.get("content") or "")
                existing_norm = existing_content.strip().lower()
                if existing_norm == content_norm:
                    _register_mesh(memory["id"], existing_content or content, category)
                    return {
                        "success": True,
                        "message": "Souvenir déjà enregistré (dédoublonnage)",
                        "memory": memory,
                        "duplicate": True,
                    }
                if len(content_norm) > 20 and len(existing_norm) > 20:
                    if content_norm in existing_norm or existing_norm in content_norm:
                        if len(content_norm) > len(existing_norm):
                            try:
                                db.update_memory(memory["id"], content)
                                _register_mesh(memory["id"], content, category)
                                return {
                                    "success": True,
                                    "message": "Souvenir existant mis à jour avec plus de détails",
                                    "memory": {**memory, "content": content},
                                    "updated": True,
                                }
                            except Exception:
                                pass
                        return {
                            "success": True,
                            "message": "Souvenir similaire déjà enregistré",
                            "memory": memory,
                            "duplicate": True,
                        }
        except Exception:
            pass

        memory = db.create_memory(content, category)
        _register_mesh(memory["id"], content, category)
        await _index_memory(memory["id"], content, category)
        return {"success": True, "message": "Souvenir enregistré", "memory": memory}
    except Exception as exc:
        return {"error": str(exc)}


async def list_memories(_args: dict[str, Any]) -> dict[str, Any]:
    try:
        memories = db.get_memories()
        return {"success": True, "count": len(memories), "memories": memories}
    except Exception as exc:
        return {"error": str(exc)}


async def delete(args: dict[str, Any]) -> dict[str, Any]:
    memory_id = str(args.get("id") or "")
    if not memory_id:
        return {"error": "ID de souvenir requis"}
    if not args.get("confirmed"):
        try:
            memories = db.get_memories()
            preview_memory = next(
                (memory for memory in memories if memory["id"] == memory_id), None
            )
            if preview_memory:
                content = str(preview_memory.get("content") or "")
                preview = content[:80] + ("…" if len(content) > 80 else "")
                label = f"« {preview} »"
            else:
                label = f"ID {memory_id}"
        except Exception:
            label = f"ID {memory_id}"
        return {
            "requiresConfirmation": True,
            "message": f"Oublier définitivement le souvenir {label} ?",
        }
    try:
        db.delete_memory(memory_id)
        await _delete_memory_index(memory_id)
        return {"success": True, "message": f"Souvenir oublié : {memory_id}"}
    except Exception as exc:
        return {"error": str(exc)}


async def search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "Requête vide"}
    try:
        limit = max(1, min(int(args.get("limit", 5)), 20))
    except (TypeError, ValueError):
        return {"error": "Limite invalide : entier attendu entre 1 et 20"}

    try:
        results = await _semantic_search(query, limit)
        if results:
            return {
                "success": True,
                "query": query,
                "count": len(results),
                "results": results,
                "mode": "semantic",
            }
    except Exception:
        pass

    try:
        memories = db.get_memories()
        query_lower = query.lower()
        matched = [
            memory
            for memory in memories
            if query_lower in str(memory.get("content") or "").lower()
        ][:limit]
        return {
            "success": True,
            "query": query,
            "count": len(matched),
            "results": matched,
            "mode": "text_filter",
        }
    except Exception as exc:
        return {"error": str(exc)}
