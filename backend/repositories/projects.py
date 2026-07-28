"""Persistance injectable des projets et de leurs instructions."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


class ProjectRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(projects)").fetchall()
        }
        if "instructions" not in columns:
            connection.execute("ALTER TABLE projects ADD COLUMN instructions TEXT")

    def list_all(self) -> list[dict]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def get(self, project_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return row_to_dict(row)

    def create(self, name: str, instructions: str | None = None) -> dict:
        project_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "INSERT INTO projects (id, name, instructions) VALUES (?, ?, ?)",
                (project_id, name, instructions),
            )
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("Le projet créé est introuvable avant commit.")
        return result

    def update(
        self,
        project_id: str,
        name: str | None = None,
        instructions: str | None = None,
    ) -> dict | None:
        assignments: list[str] = []
        values: list[object] = []
        if name is not None:
            assignments.append("name = ?")
            values.append(name)
        if instructions is not None:
            assignments.append("instructions = ?")
            values.append(instructions)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if assignments:
                assignments.append("updated_at = datetime('now')")
                connection.execute(
                    f"UPDATE projects SET {', '.join(assignments)} WHERE id = ?",
                    (*values, project_id),
                )
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return row_to_dict(row)

    def delete(self, project_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))


repository = ProjectRepository()
get_projects = repository.list_all
get_project = repository.get
create_project = repository.create
update_project = repository.update
delete_project = repository.delete
