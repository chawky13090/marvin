"""Régressions du domaine Tâches/Notes et de sa façade tools.py."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tool_domains import productivity


async def _run() -> None:
    assert productivity.parse_tags(" urgent, réseau, , urgent ") == [
        "urgent", "réseau", "urgent"
    ]
    assert productivity.parse_tags([" a ", "", 3]) == ["a", "3"]

    created_task = {"id": "t1", "title": "Configurer le réseau"}
    with patch.object(productivity.db, "create_task", return_value=created_task) as create:
        result = await productivity.task_create({
            "title": "Configurer le réseau", "tags": "réseau, urgent"
        })
    assert result["success"] is True and result["task"] == created_task
    assert create.call_args.kwargs["tags"] == ["réseau", "urgent"]

    with patch.object(productivity.db, "list_tasks", return_value=[created_task]) as listing:
        result = await productivity.task_list({"status": "all", "priority": "high"})
    assert result["count"] == 1
    listing.assert_called_once_with(status=None, priority="high")

    with patch.object(productivity.db, "update_task", return_value={**created_task, "status": "done"}) as update:
        result = await productivity.task_update({"id": "t1", "status": "completed"})
    assert result["success"] is True
    assert update.call_args.args[1]["status"] == "done"
    invalid = await productivity.task_update({"id": "t1", "status": 4})
    assert "texte attendu" in invalid["error"]

    with patch.object(productivity.db, "get_task", return_value=created_task):
        confirmation = await productivity.task_delete({"id": "t1"})
    assert confirmation["requiresConfirmation"] is True
    with (
        patch.object(productivity.db, "get_task", return_value=created_task),
        patch.object(productivity.db, "delete_task") as delete,
    ):
        deleted = await productivity.task_delete({"id": "t1", "confirmed": True})
    assert deleted["success"] is True
    delete.assert_called_once_with("t1")

    note = {"id": "n1", "title": "Runbook", "content": "Contenu", "tags": ["ops"]}
    index = AsyncMock(return_value=None)
    with (
        patch.object(productivity.db, "create_note", return_value=note),
        patch.object(productivity, "_index_note", index),
    ):
        created = await productivity.note_create({"title": "Runbook", "tags": "ops"})
    assert created["success"] is True
    index.assert_awaited_once_with(note)

    with patch.object(productivity.db, "list_notes", return_value=[note]) as listing:
        result = await productivity.note_list({"tag": "ops", "pinned": True})
    assert result["count"] == 1
    listing.assert_called_once_with(search="ops", pinned=True)

    with (
        patch.object(productivity.db, "update_note", return_value=note) as update,
        patch.object(productivity, "_index_note", AsyncMock(return_value=None)),
    ):
        updated = await productivity.note_update({"id": "n1", "tags": "ops, doc"})
    assert updated["success"] is True
    assert update.call_args.args[1]["tags"] == ["ops", "doc"]

    remove_index = AsyncMock(return_value=None)
    with (
        patch.object(productivity.db, "get_note", return_value=note),
        patch.object(productivity.db, "delete_note") as delete,
        patch.object(productivity, "_delete_note_index", remove_index),
    ):
        deleted = await productivity.note_delete({"id": "n1", "confirmed": True})
    assert deleted["success"] is True
    delete.assert_called_once_with("n1")
    remove_index.assert_awaited_once_with("n1")


def main() -> int:
    asyncio.run(_run())
    import tools

    expected = {
        "task_create": productivity.task_create,
        "task_list": productivity.task_list,
        "task_update": productivity.task_update,
        "task_delete": productivity.task_delete,
        "note_create": productivity.note_create,
        "note_list": productivity.note_list,
        "note_update": productivity.note_update,
        "note_delete": productivity.note_delete,
    }
    for name, function in expected.items():
        assert tools.TOOLS_REGISTRY[name] is function, name
        assert any(spec["function"]["name"] == name for spec in tools.TOOLS_SPEC), name
    assert len(tools.TOOLS_REGISTRY) == len(tools.TOOLS_SPEC) == 344
    print("Tool Domain Productivity OK - tâches, notes, index et façade 344/344.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
