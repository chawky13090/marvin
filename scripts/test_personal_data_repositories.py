"""Régressions SQLite des repositories mémoires, tâches et notes."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.memories import MemoryRepository
from repositories.notes import NoteRepository
from repositories.tasks import TaskRepository


def _create_schema(path: Path) -> None:
    with db(path) as connection:
        connection.executescript(
            """CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL
                    CHECK(category IN ('user_profile', 'preference', 'fact', 'habit')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'in_progress', 'done', 'cancelled')),
                priority TEXT NOT NULL DEFAULT 'medium'
                    CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
                due_date TEXT,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                tags TEXT DEFAULT '[]',
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );"""
        )


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "personal.db"
        _create_schema(path)
        scope = lambda: db(path)
        memories = MemoryRepository(connection_scope=scope)
        tasks = TaskRepository(connection_scope=scope)
        notes = NoteRepository(connection_scope=scope)

        with patch("repositories.memories.uuid.uuid4", return_value="memory-1"):
            memory = memories.create("Préférence durable", "preference")
        assert memory == {
            "id": "memory-1",
            "category": "preference",
            "content": "Préférence durable",
        }
        assert memories.list_all()[0]["id"] == "memory-1"
        assert memories.update("missing", "x") is None
        updated_memory = memories.update("memory-1", content="Préférence confirmée")
        assert updated_memory["content"] == "Préférence confirmée"
        assert updated_memory["category"] == "preference"

        with patch("repositories.tasks.uuid.uuid4", return_value="task-1"):
            task = tasks.create(
                "Déployer",
                description="Production",
                priority="urgent",
                due_date="2026-08-01",
                tags=["ops", "client"],
            )
        assert task["tags"] == ["ops", "client"] and task["status"] == "pending"
        assert tasks.list(priority="urgent")[0]["id"] == "task-1"
        updated_task = tasks.update(
            "task-1",
            {"status": "done", "tags": ["validé"], "unknown": "ignored"},
        )
        assert updated_task["status"] == "done" and updated_task["tags"] == ["validé"]
        assert tasks.update("missing", {"title": "absent"}) is None

        with patch("repositories.notes.uuid.uuid4", return_value="note-1"):
            note = notes.create(
                "Runbook",
                content="Procédure",
                tags=["ops"],
                pinned=True,
            )
        assert note["pinned"] is True and note["tags"] == ["ops"]
        assert notes.list(search="Proc", pinned=True)[0]["id"] == "note-1"
        updated_note = notes.update(
            "note-1",
            {"content": "Procédure validée", "pinned": False, "ignored": "x"},
        )
        assert updated_note["content"] == "Procédure validée"
        assert updated_note["pinned"] is False
        assert notes.update("missing", {"title": "absente"}) is None

        with db(path) as connection:
            connection.execute("UPDATE tasks SET tags='invalid-json' WHERE id='task-1'")
            connection.execute("UPDATE notes SET tags='invalid-json' WHERE id='note-1'")
        assert tasks.get("task-1")["tags"] == []
        assert notes.get("note-1")["tags"] == []

        with patch("repositories.memories.uuid.uuid4", return_value="memory-1"):
            try:
                memories.create("Collision", "fact")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Une clé dupliquée doit annuler la transaction.")
        assert memories.list_all()[0]["content"] == "Préférence confirmée"

        tasks.delete("task-1")
        notes.delete("note-1")
        memories.clear()
        assert tasks.get("task-1") is None
        assert notes.get("note-1") is None
        assert memories.list_all() == []

    import database
    from repositories import memories as memory_module
    from repositories import notes as note_module
    from repositories import tasks as task_module

    expected = {
        "create_memory": memory_module.create_memory,
        "get_memories": memory_module.get_memories,
        "update_memory": memory_module.update_memory,
        "delete_memory": memory_module.delete_memory,
        "clear_all_memories": memory_module.clear_all_memories,
        "create_task": task_module.create_task,
        "get_task": task_module.get_task,
        "list_tasks": task_module.list_tasks,
        "update_task": task_module.update_task,
        "delete_task": task_module.delete_task,
        "create_note": note_module.create_note,
        "get_note": note_module.get_note,
        "list_notes": note_module.list_notes,
        "update_note": note_module.update_note,
        "delete_note": note_module.delete_note,
    }
    for name, function in expected.items():
        assert getattr(database, name) is function, name

    print(
        "Personal Data Repositories OK - mémoires, tâches, notes, JSON, filtres, "
        "rollback et façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
