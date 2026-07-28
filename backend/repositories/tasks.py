"""Persistance injectable des tâches personnelles de Marvin."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


def _parse_task(row: dict | None) -> dict | None:
    if row is None:
        return None
    if row.get("tags") and isinstance(row["tags"], str):
        try:
            row["tags"] = json.loads(row["tags"])
        except json.JSONDecodeError:
            row["tags"] = []
    return row


class TaskRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    def create(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        due_date: str | None = None,
        tags: list | None = None,
    ) -> dict:
        task_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            connection.execute(
                """INSERT INTO tasks (id, title, description, priority, due_date, tags)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    title,
                    description,
                    priority,
                    due_date,
                    json.dumps(tags or []),
                ),
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        result = _parse_task(row_to_dict(row))
        if result is None:
            raise RuntimeError("La tâche créée est introuvable avant commit.")
        return result

    def get(self, task_id: str) -> dict | None:
        with self._connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return _parse_task(row_to_dict(row))

    def list(
        self,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list[object] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if priority:
            sql += " AND priority = ?"
            params.append(priority)
        sql += (
            " ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 "
            "WHEN 'medium' THEN 3 ELSE 4 END, created_at DESC LIMIT ?"
        )
        params.append(limit)
        with self._connection_scope() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_parse_task(row_to_dict(row)) for row in rows]

    def update(self, task_id: str, updates: dict) -> dict | None:
        fields: list[str] = []
        values: list[object] = []
        for key in ("title", "description", "status", "priority", "due_date"):
            if key in updates:
                fields.append(f"{key} = ?")
                values.append(updates[key])
        if "tags" in updates:
            fields.append("tags = ?")
            values.append(json.dumps(updates["tags"]))
        if not fields:
            return self.get(task_id)
        fields.append("updated_at = datetime('now')")
        values.append(task_id)
        with self._connection_scope() as connection:
            connection.execute(
                f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return _parse_task(row_to_dict(row))

    def delete(self, task_id: str) -> None:
        with self._connection_scope() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


repository = TaskRepository()
create_task = repository.create
get_task = repository.get
list_tasks = repository.list
update_task = repository.update
delete_task = repository.delete
