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
    invalid_category = await memory_domain.save({
        "content": "Ne doit pas être écrit",
        "category": "working",
    })
    assert "prise en charge" in invalid_category["error"]

    existing = {"id": "m1", "content": "Le routeur principal est R1", "category": "fact"}
    with (
        patch.object(memory_domain.db, "get_memories", return_value=[existing]),
        patch.object(
            memory_domain.memory_lifecycle,
            "refresh",
            AsyncMock(return_value={"consistency": "complete", "warnings": []}),
        ) as refresh,
    ):
        duplicate = await memory_domain.save({
            "content": "Le routeur principal est R1", "category": "fact"
        })
    assert duplicate["duplicate"] is True
    refresh.assert_awaited_once_with(existing, source="chat")

    longer = "Le routeur principal est R1 et son adresse de gestion est documentée"
    with (
        patch.object(memory_domain.db, "get_memories", return_value=[existing]),
        patch.object(
            memory_domain.db,
            "update_memory",
            return_value={**existing, "content": longer},
        ) as update,
        patch.object(
            memory_domain.memory_lifecycle,
            "refresh",
            AsyncMock(return_value={"consistency": "complete", "warnings": []}),
        ) as refresh,
    ):
        updated = await memory_domain.save({"content": longer, "category": "fact"})
    assert updated["updated"] is True
    update.assert_called_once_with("m1", longer)
    refresh.assert_awaited_once_with(
        {**existing, "content": longer},
        source="chat",
    )

    created_memory = {"id": "m2", "content": "Nouvelle préférence", "category": "preference"}
    with (
        patch.object(memory_domain.db, "get_memories", return_value=[]),
        patch.object(
            memory_domain.memory_lifecycle,
            "create",
            AsyncMock(return_value={
                **created_memory,
                "consistency": "complete",
                "warnings": [],
            }),
        ) as create,
    ):
        created = await memory_domain.save({
            "content": " Nouvelle préférence ", "category": "preference"
        })
    assert created["success"] is True
    create.assert_awaited_once_with(
        "Nouvelle préférence",
        "preference",
        source="chat",
    )
    assert created["consistency"] == "complete"

    with patch.object(memory_domain.db, "get_memories", return_value=[existing]):
        listed = await memory_domain.list_memories({})
        confirmation = await memory_domain.delete({"id": "m1"})
    assert listed["count"] == 1
    assert confirmation["requiresConfirmation"] is True and "routeur" in confirmation["message"]

    with (
        patch.object(
            memory_domain.memory_lifecycle,
            "forget",
            AsyncMock(return_value={"success": True, "forgotten": True, "id": "m1"}),
        ) as forget,
    ):
        removed = await memory_domain.delete({"id": "m1", "confirmed": True})
    assert removed["success"] is True
    forget.assert_awaited_once_with("m1")

    with patch.object(
        memory_domain.memory_lifecycle,
        "forget",
        AsyncMock(return_value={
            "success": False,
            "forgotten": False,
            "stage": "index",
            "error_type": "RuntimeError",
        }),
    ):
        incomplete = await memory_domain.delete({"id": "m1", "confirmed": True})
    assert incomplete["forgotten"] is False
    assert "complet" in incomplete["error"]

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
    assert len(tools.TOOLS_REGISTRY) == len(tools.TOOLS_SPEC) == 346
    print("Tool Domain Memory OK - dédoublonnage, Mesh, Qdrant, repli et façade 346/346.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
