"""Persistance injectable des souvenirs explicites de Marvin."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


class MemoryRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    def create(self, content: str, category: str = "fact") -> dict:
        memory_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            connection.execute(
                "INSERT INTO memories (id, category, content) VALUES (?, ?, ?)",
                (memory_id, category, content),
            )
        return {"id": memory_id, "category": category, "content": content}

    def list_all(self) -> list[dict]:
        with self._connection_scope() as connection:
            rows = connection.execute(
                "SELECT * FROM memories ORDER BY created_at DESC"
            ).fetchall()
        return [row_to_dict(row) for row in rows]

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
            connection.execute(
                """UPDATE memories
                   SET content = ?, category = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (
                    content if content is not None else existing["content"],
                    category if category is not None else existing["category"],
                    memory_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return row_to_dict(row)


repository = MemoryRepository()
create_memory = repository.create
get_memories = repository.list_all
delete_memory = repository.delete
clear_all_memories = repository.clear
update_memory = repository.update
