"""Contrats du cycle de vie cohérent SQLite, Mesh et index mémoire."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import memory_lifecycle
import memory_consolidation
import memory_mesh
from api import memories as memories_api
from fastapi import HTTPException


async def _exercise(mesh_path: Path) -> None:
    old_mesh = memory_mesh.MESH_PATH
    memory_mesh.MESH_PATH = mesh_path
    try:
        created = {
            "id": "memory-1",
            "content": "Préférence de test",
            "category": "preference",
        }
        with (
            patch.object(memory_lifecycle.db, "create_memory", return_value=created),
            patch.object(memory_lifecycle, "_index", AsyncMock()),
        ):
            result = await memory_lifecycle.create(
                created["content"],
                created["category"],
                source="test",
            )
        assert result["consistency"] == "complete"
        assert memory_mesh.list_metadata()[0]["memory_id"] == "memory-1"
        assert memory_mesh.list_metadata()[0]["source"] == "test"
        try:
            await memory_lifecycle.create("test", "working", source="test")
        except ValueError:
            pass
        else:
            raise AssertionError("Une catégorie hors schéma devait être refusée avant SQLite.")

        memory_mesh.register(
            "working-1",
            "Contexte temporaire",
            "working",
            source="test",
        )
        future = datetime.now(timezone.utc) + timedelta(days=8)
        assert memory_mesh.expired_ids(now=future) == {"working-1"}
        assert memory_mesh.filter_active(
            [{"id": "working-1"}, {"id": "legacy"}],
            now=future,
        ) == [{"id": "legacy"}]

        corrupt_path = mesh_path.with_name("corrupt.json")
        corrupt_path.write_text("{invalid", encoding="utf-8")
        memory_mesh.MESH_PATH = corrupt_path
        try:
            memory_mesh.register("never-written", "test", "fact")
        except memory_mesh.MemoryMeshError:
            pass
        else:
            raise AssertionError("Un Mesh corrompu ne devait jamais être remplacé.")
        assert corrupt_path.read_text(encoding="utf-8") == "{invalid"
        memory_mesh.MESH_PATH = mesh_path

        corrupt_path = mesh_path.with_name("corrupt.json")
        corrupt_path.write_text("{invalid", encoding="utf-8")
        memory_mesh.MESH_PATH = corrupt_path
        try:
            memory_mesh.register("never-written", "test", "fact")
        except memory_mesh.MemoryMeshError:
            pass
        else:
            raise AssertionError("Un Mesh corrompu ne devait jamais être remplacé.")
        assert corrupt_path.read_text(encoding="utf-8") == "{invalid"
        memory_mesh.MESH_PATH = mesh_path

        with (
            patch.object(memory_lifecycle.memory_mesh, "expired_ids", return_value={"working-1"}),
            patch.object(
                memory_lifecycle,
                "forget",
                AsyncMock(return_value={
                    "success": True,
                    "forgotten": True,
                    "id": "working-1",
                }),
            ) as forget_expired,
        ):
            pruned = await memory_lifecycle.prune_expired()
        assert pruned["forgotten_count"] == 1
        forget_expired.assert_awaited_once_with("working-1")

        order: list[str] = []
        original_remove = memory_mesh.remove

        async def delete_index(_memory_id: str) -> None:
            order.append("index")

        def remove_mesh(memory_id: str) -> bool:
            order.append("mesh")
            return original_remove(memory_id)

        def delete_database(_memory_id: str) -> None:
            order.append("database")

        with (
            patch.object(memory_lifecycle, "_delete_index", delete_index),
            patch.object(memory_lifecycle.memory_mesh, "remove", remove_mesh),
            patch.object(memory_lifecycle.db, "delete_memory", delete_database),
        ):
            forgotten = await memory_lifecycle.forget("memory-1")
        assert forgotten["forgotten"] is True
        assert order == ["index", "mesh", "database"]
        assert {
            item["memory_id"] for item in memory_mesh.list_metadata()
        } == {"working-1"}

        with (
            patch.object(
                memory_lifecycle,
                "_delete_index",
                AsyncMock(side_effect=RuntimeError("Qdrant indisponible")),
            ),
            patch.object(memory_lifecycle.memory_mesh, "remove") as remove,
            patch.object(memory_lifecycle.db, "delete_memory") as delete,
        ):
            refused = await memory_lifecycle.forget("memory-2")
        assert refused == {
            "success": False,
            "forgotten": False,
            "stage": "index",
            "error_type": "RuntimeError",
        }
        remove.assert_not_called()
        delete.assert_not_called()

        with (
            patch.object(memory_lifecycle.db, "get_memories", return_value=[
                {"id": "a"}, {"id": "b"},
            ]),
            patch.object(
                memory_lifecycle,
                "forget",
                AsyncMock(side_effect=[
                    {"success": True, "forgotten": True, "id": "a"},
                    {
                        "success": False,
                        "forgotten": False,
                        "stage": "mesh",
                        "error_type": "OSError",
                    },
                ]),
            ),
        ):
            cleared = await memory_lifecycle.clear_all()
        assert cleared["success"] is False
        assert cleared["forgotten_count"] == 1
        assert cleared["failure_count"] == 1
        assert cleared["failures"][0] == {
            "id": "b",
            "stage": "mesh",
            "error_type": "OSError",
        }

        duplicate_memories = [
            {
                "id": "short",
                "content": "Le serveur de test utilise Debian 13 systemd",
                "category": "fact",
            },
            {
                "id": "long",
                "content": "Le serveur de test utilise Debian 13 systemd actif",
                "category": "fact",
            },
        ]
        with (
            patch.object(
                memory_consolidation.db,
                "get_memories",
                return_value=duplicate_memories,
            ),
            patch.object(
                memory_consolidation.memory_lifecycle,
                "forget",
                AsyncMock(return_value={
                    "success": True,
                    "forgotten": True,
                    "id": "short",
                }),
            ) as forget_duplicate,
        ):
            preview = await memory_consolidation.consolidate_memories(dry_run=True)
            consolidated = await memory_consolidation.consolidate_memories()
        assert preview["merged_count"] == 1 and preview["dry_run"] is True
        assert consolidated["merged_count"] == 1
        forget_duplicate.assert_awaited_once_with("short")

        with (
            patch.object(
                memory_consolidation.db,
                "get_memories",
                return_value=duplicate_memories,
            ),
            patch.object(
                memory_consolidation.memory_lifecycle,
                "forget",
                AsyncMock(return_value={
                    "success": False,
                    "forgotten": False,
                    "stage": "index",
                    "error_type": "RuntimeError",
                }),
            ),
        ):
            consolidation_failure = await memory_consolidation.consolidate_memories()
        assert consolidation_failure["success"] is False
        assert consolidation_failure["merged_count"] == 0
        assert consolidation_failure["failures"][0]["id"] == "short"

        with patch.object(
            memories_api.memory_lifecycle,
            "create",
            AsyncMock(return_value={
                "id": "api-1",
                "content": "Souvenir API",
                "category": "fact",
                "consistency": "complete",
                "warnings": [],
            }),
        ) as api_create:
            api_memory = await memories_api.create_memory(
                memories_api.MemoryCreate(content=" Souvenir API ", category="fact")
            )
        assert api_memory["id"] == "api-1"
        api_create.assert_awaited_once_with("Souvenir API", "fact", source="api")

        try:
            await memories_api.clear_memories(confirmed=False)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("L'oubli global sans confirmation devait être refusé.")

        with patch.object(
            memories_api.memory_lifecycle,
            "forget",
            AsyncMock(return_value={
                "success": False,
                "forgotten": False,
                "stage": "index",
                "error_type": "RuntimeError",
            }),
        ):
            try:
                await memories_api.delete_memory("api-1")
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("Un oubli incomplet ne devait pas retourner un succès.")
        settings_proxy = (
            ROOT / "app" / "api" / "settings" / "route.js"
        ).read_text(encoding="utf-8")
        assert "/api/memories?confirmed=true" in settings_proxy
    finally:
        memory_mesh.MESH_PATH = old_mesh


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-memory-lifecycle-") as directory:
        asyncio.run(_exercise(Path(directory) / "mesh.json"))
    print("Memory Lifecycle OK - ordre d'oubli, cohérence et panne partielle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
