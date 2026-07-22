"""Régressions du domaine Mémoire et de sa façade tools.py."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tool_domains import memory as memory_domain


async def _run() -> None:
    existing = {"id": "m1", "content": "Le routeur principal est R1", "category": "fact"}
    with (
        patch.object(memory_domain.db, "get_memories", return_value=[existing]),
        patch.object(memory_domain, "_register_mesh") as register,
    ):
        duplicate = await memory_domain.save({
            "content": "Le routeur principal est R1", "category": "fact"
        })
    assert duplicate["duplicate"] is True
    register.assert_called_once_with("m1", existing["content"], "fact")

    longer = "Le routeur principal est R1 et son adresse de gestion est documentée"
    with (
        patch.object(memory_domain.db, "get_memories", return_value=[existing]),
        patch.object(memory_domain.db, "update_memory") as update,
        patch.object(memory_domain, "_register_mesh"),
    ):
        updated = await memory_domain.save({"content": longer, "category": "fact"})
    assert updated["updated"] is True
    update.assert_called_once_with("m1", longer)

    created_memory = {"id": "m2", "content": "Nouvelle préférence", "category": "preference"}
    index = AsyncMock(return_value=None)
    with (
        patch.object(memory_domain.db, "get_memories", return_value=[]),
        patch.object(memory_domain.db, "create_memory", return_value=created_memory),
        patch.object(memory_domain, "_register_mesh") as register,
        patch.object(memory_domain, "_index_memory", index),
    ):
        created = await memory_domain.save({
            "content": " Nouvelle préférence ", "category": "preference"
        })
    assert created["success"] is True
    register.assert_called_once_with("m2", "Nouvelle préférence", "preference")
    index.assert_awaited_once_with("m2", "Nouvelle préférence", "preference")

    with patch.object(memory_domain.db, "get_memories", return_value=[existing]):
        listed = await memory_domain.list_memories({})
        confirmation = await memory_domain.delete({"id": "m1"})
    assert listed["count"] == 1
    assert confirmation["requiresConfirmation"] is True and "routeur" in confirmation["message"]

    remove_index = AsyncMock(return_value=None)
    with (
        patch.object(memory_domain.db, "delete_memory") as delete,
        patch.object(memory_domain, "_delete_memory_index", remove_index),
    ):
        removed = await memory_domain.delete({"id": "m1", "confirmed": True})
    assert removed["success"] is True
    delete.assert_called_once_with("m1")
    remove_index.assert_awaited_once_with("m1")

    semantic_search = AsyncMock(return_value=[{"id": "m1", "score": 0.9}])
    with patch.object(memory_domain, "_semantic_search", semantic_search):
        semantic = await memory_domain.search({"query": "routeur", "limit": 3})
    assert semantic["mode"] == "semantic" and semantic["count"] == 1
    semantic_search.assert_awaited_once_with("routeur", 3)

    with (
        patch.object(memory_domain, "_semantic_search", AsyncMock(side_effect=RuntimeError("Qdrant HS"))),
        patch.object(memory_domain.db, "get_memories", return_value=[existing, created_memory]),
    ):
        fallback = await memory_domain.search({"query": "ROUTEUR", "limit": 50})
    assert fallback["mode"] == "text_filter" and fallback["results"] == [existing]
    assert "Limite invalide" in (await memory_domain.search({"query": "x", "limit": "abc"}))["error"]


def main() -> int:
    asyncio.run(_run())
    import tools

    expected = {
        "memory_save": memory_domain.save,
        "memory_list": memory_domain.list_memories,
        "memory_delete": memory_domain.delete,
        "memory_search": memory_domain.search,
    }
    for name, function in expected.items():
        assert tools.TOOLS_REGISTRY[name] is function, name
        assert any(spec["function"]["name"] == name for spec in tools.TOOLS_SPEC), name
    assert len(tools.TOOLS_REGISTRY) == len(tools.TOOLS_SPEC) == 344
    print("Tool Domain Memory OK - dédoublonnage, Mesh, Qdrant, repli et façade 344/344.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
