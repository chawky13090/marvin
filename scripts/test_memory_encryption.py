"""Régressions du chiffrement actif SQLite et Qdrant des souvenirs."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from db_connection import db
import memory_cipher
import memory_lifecycle
from repositories.memories import MemoryRepository
import vector_store


def _protect(value: bytes) -> bytes:
    return b"sealed:" + value[::-1]


def _unprotect(value: bytes) -> bytes:
    if not value.startswith(b"sealed:"):
        raise ValueError("invalid")
    return value[len(b"sealed:") :][::-1]


def test_cipher_contract() -> None:
    content = "donnée privée " * 5_000
    protected = memory_cipher.protect_text(content, protect=_protect)
    assert protected.startswith(memory_cipher.PREFIX)
    assert content not in protected
    assert memory_cipher.unprotect_text(protected, unprotect=_unprotect) == content
    try:
        memory_cipher.unprotect_text(memory_cipher.PREFIX + '["%%%"]', unprotect=_unprotect)
    except memory_cipher.MemoryCipherError:
        pass
    else:
        raise AssertionError("Une enveloppe corrompue doit échouer fermée.")


def _schema(path: Path) -> None:
    with db(path) as connection:
        connection.execute(
            """CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )


def test_sqlite_migration_and_crud() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-memory-encryption-") as directory:
        path = Path(directory) / "memory.db"
        empty_path = Path(directory) / "empty.db"
        with db(empty_path) as empty_connection:
            MemoryRepository(connection_scope=lambda: db(empty_path)).ensure_schema(
                empty_connection
            )
        _schema(path)
        with db(path) as connection:
            connection.execute(
                "INSERT INTO memories(id, category, content) VALUES (?, ?, ?)",
                ("legacy", "fact", "contenu historique privé"),
            )
        repository = MemoryRepository(connection_scope=lambda: db(path))
        with db(path) as connection:
            repository.ensure_schema(connection)
        with db(path) as connection:
            raw = connection.execute(
                "SELECT content FROM memories WHERE id='legacy'"
            ).fetchone()[0]
        assert memory_cipher.is_protected(raw)
        assert "contenu historique privé" not in raw
        assert repository.list_all()[0]["content"] == "contenu historique privé"
        created = repository.create("préférence secrète", "preference")
        assert created["content"] == "préférence secrète"
        with db(path) as connection:
            stored = connection.execute(
                "SELECT content FROM memories WHERE id=?", (created["id"],)
            ).fetchone()[0]
        assert memory_cipher.is_protected(stored)
        assert repository.update(created["id"], "nouvelle préférence")["content"] == "nouvelle préférence"
        with db(path) as connection:
            assert repository.rollback_encryption(connection) == 2
        with db(path) as connection:
            values = {
                row["content"]
                for row in connection.execute("SELECT content FROM memories").fetchall()
            }
        assert values == {"contenu historique privé", "nouvelle préférence"}


class FakeQdrant:
    def __init__(self) -> None:
        self.payload = {
            "text": "souvenir qdrant privé",
            "category": "fact",
            "original_id": "memory-1",
        }

    def scroll(self, **_kwargs):
        return [SimpleNamespace(id="point-1", payload=dict(self.payload))], None

    def overwrite_payload(self, *, payload, **_kwargs):
        self.payload = dict(payload)

    def delete(self, **_kwargs):
        self.payload = {}


def test_qdrant_payload_migration() -> None:
    client = FakeQdrant()
    assert vector_store._migrate_memory_payloads(client) == 1
    assert "text" not in client.payload
    assert memory_cipher.is_protected(client.payload["text_protected"])
    assert vector_store._memory_payload_text(client.payload) == "souvenir qdrant privé"
    assert vector_store._migrate_memory_payloads(client) == 0
    assert vector_store.rollback_memory_payload_protection(client) == 1
    assert client.payload["text"] == "souvenir qdrant privé"
    assert "text_protected" not in client.payload


def test_qdrant_audit_has_no_content() -> None:
    client = FakeQdrant()
    vector_store._migrate_memory_payloads(client)
    previous_client = vector_store._client
    previous_migrated = vector_store._memory_payloads_migrated
    vector_store._client = client
    vector_store._memory_payloads_migrated = True
    try:
        report = vector_store.inspect_memory_index({
            "memory-1": client.payload["content_sha256"]
            if "content_sha256" in client.payload
            else "missing-hash"
        })
    finally:
        vector_store._client = previous_client
        vector_store._memory_payloads_migrated = previous_migrated
    assert report["available"] is True
    assert set(report) == {
        "available", "count", "missing", "orphan", "stale", "unprotected", "corrupt"
    }
    assert "souvenir qdrant privé" not in str(report)


def test_repair_removes_index_orphan() -> None:
    before = {
        "missing_mesh": [],
        "stale_content": [],
        "invalid_metadata": [],
        "orphan_mesh": [],
        "index": {
            "available": True,
            "missing": [],
            "orphan": ["orphan-1"],
            "stale": [],
            "unprotected": [],
            "corrupt": [],
        },
    }
    after = {**before, "consistent": True, "index": {**before["index"], "orphan": []}}

    async def exercise() -> None:
        with (
            patch.object(memory_lifecycle, "audit_consistency", side_effect=[before, after]),
            patch.object(memory_lifecycle.db, "get_memories", return_value=[]),
            patch.object(memory_lifecycle, "_delete_index", AsyncMock()) as delete,
        ):
            result = await memory_lifecycle.repair_consistency(dry_run=False)
        assert result["success"] is True
        delete.assert_awaited_once_with("orphan-1")
        assert result["actions"] == [
            {"id": "orphan-1", "action": "remove_index_orphan"}
        ]

    asyncio.run(exercise())


def main() -> int:
    test_cipher_contract()
    test_sqlite_migration_and_crud()
    test_qdrant_payload_migration()
    test_qdrant_audit_has_no_content()
    test_repair_removes_index_orphan()
    print("Memory Encryption OK - DPAPI chunké, migration SQLite/Qdrant et CRUD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
