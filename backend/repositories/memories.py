"""Persistance injectable des souvenirs explicites de Marvin."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict
import memory_cipher


ConnectionScope = Callable[[], AbstractContextManager]


class MemoryRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def _project(row) -> dict:
        item = row_to_dict(row)
        if item is None:
            raise memory_cipher.MemoryCipherError("Souvenir SQLite absent.")
        item["content"] = memory_cipher.unprotect_text(
            item["content"],
            allow_plaintext=True,
        )
        return item

    def ensure_schema(self, connection) -> None:
        """Migre le clair historique après chiffrement et relecture réussis."""
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchone()
        if exists is None:
            return
        rows = connection.execute("SELECT id, content FROM memories").fetchall()
        for row in rows:
            content = str(row["content"])
            if memory_cipher.is_protected(content):
                memory_cipher.unprotect_text(content)
                continue
            protected = memory_cipher.protect_text(content)
            if memory_cipher.unprotect_text(protected) != content:
                raise memory_cipher.MemoryCipherError(
                    "La migration mémoire n'est pas vérifiable."
                )
            connection.execute(
                "UPDATE memories SET content = ? WHERE id = ?",
                (protected, row["id"]),
            )

    @staticmethod
    def rollback_encryption(connection) -> int:
        """Rend le schéma lisible par une version antérieure, Marvin arrêté."""
        changed = 0
        rows = connection.execute("SELECT id, content FROM memories").fetchall()
        for row in rows:
            content = str(row["content"])
            if not memory_cipher.is_protected(content):
                continue
            plaintext = memory_cipher.unprotect_text(content)
            connection.execute(
                "UPDATE memories SET content = ? WHERE id = ?",
                (plaintext, row["id"]),
            )
            changed += 1
        return changed

    def create(self, content: str, category: str = "fact") -> dict:
        memory_id = str(uuid.uuid4())
        protected = memory_cipher.protect_text(content)
        with self._connection_scope() as connection:
            connection.execute(
                "INSERT INTO memories (id, category, content) VALUES (?, ?, ?)",
                (memory_id, category, protected),
            )
        return {"id": memory_id, "category": category, "content": content}

    def list_all(self) -> list[dict]:
        with self._connection_scope() as connection:
            rows = connection.execute(
                "SELECT * FROM memories ORDER BY created_at DESC"
            ).fetchall()
        return [self._project(row) for row in rows]

    def delete(self, memory_id: str) -> None:
        with self._connection_scope() as connection:
            connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

    def clear(self) -> None:
        with self._connection_scope() as connection:
            connection.execute("DELETE FROM memories")

    def update(
        self,
        memory_id: str,
        content: str | None = None,
        category: str | None = None,
    ) -> dict | None:
        with self._connection_scope() as connection:
            existing = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if existing is None:
                return None
            existing_content = memory_cipher.unprotect_text(
                existing["content"],
                allow_plaintext=True,
            )
            next_content = content if content is not None else existing_content
            connection.execute(
                """UPDATE memories
                   SET content = ?, category = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (
                    memory_cipher.protect_text(next_content),
                    category if category is not None else existing["category"],
                    memory_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._project(row)


repository = MemoryRepository()
create_memory = repository.create
get_memories = repository.list_all
delete_memory = repository.delete
clear_all_memories = repository.clear
update_memory = repository.update
