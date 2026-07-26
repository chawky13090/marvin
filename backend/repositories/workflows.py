"""Repository transactionnel des workflows et de leurs exécutions."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


class WorkflowRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                steps TEXT DEFAULT '[]',
                last_run TEXT,
                run_count INTEGER NOT NULL DEFAULT 0,
                last_status TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                steps_results TEXT DEFAULT '[]',
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                duration_ms INTEGER
            )"""
        )

    @staticmethod
    def _parse_json_field(row: dict[str, Any] | None, field: str) -> dict[str, Any] | None:
        if row is None:
            return None
        value = row.get(field)
        if value and isinstance(value, str):
            try:
                row[field] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                row[field] = []
        return row

    def _parse_workflow(self, row) -> dict[str, Any] | None:
        return self._parse_json_field(row_to_dict(row), "steps")

    def _parse_run(self, row) -> dict[str, Any] | None:
        return self._parse_json_field(row_to_dict(row), "steps_results")

    def create_workflow(
        self, name: str, description: str, steps: list[dict[str, Any]]
    ) -> dict[str, Any]:
        workflow_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "INSERT INTO workflows (id,name,description,steps) VALUES (?,?,?,?)",
                (workflow_id, name, description, json.dumps(steps)),
            )
            row = connection.execute(
                "SELECT * FROM workflows WHERE id=?", (workflow_id,)
            ).fetchone()
        result = self._parse_workflow(row)
        if result is None:
            raise RuntimeError("Le workflow créé est introuvable avant commit.")
        return result

    def list_workflows(self) -> list[dict[str, Any]]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                "SELECT * FROM workflows ORDER BY updated_at DESC"
            ).fetchall()
        return [self._parse_workflow(row) for row in rows]

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM workflows WHERE id=?", (workflow_id,)
            ).fetchone()
        return self._parse_workflow(row)

    def update_workflow(
        self, workflow_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        fields: list[str] = []
        values: list[Any] = []
        for name in ("name", "description", "last_run", "last_status"):
            if name in updates:
                fields.append(f"{name}=?")
                values.append(updates[name])
        if "steps" in updates:
            fields.append("steps=?")
            values.append(json.dumps(updates["steps"]))
        if "run_count" in updates:
            fields.append("run_count=run_count+1")

        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if fields:
                fields.append("updated_at=datetime('now')")
                connection.execute(
                    f"UPDATE workflows SET {', '.join(fields)} WHERE id=?",
                    (*values, workflow_id),
                )
            row = connection.execute(
                "SELECT * FROM workflows WHERE id=?", (workflow_id,)
            ).fetchone()
        return self._parse_workflow(row)

    def delete_workflow(self, workflow_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM workflow_runs WHERE workflow_id=?", (workflow_id,)
            )
            connection.execute("DELETE FROM workflows WHERE id=?", (workflow_id,))

    def create_run(self, workflow_id: str) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "INSERT INTO workflow_runs (id,workflow_id,status) VALUES (?,?,?)",
                (run_id, workflow_id, "running"),
            )
            row = connection.execute(
                "SELECT * FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
        result = self._parse_run(row)
        if result is None:
            raise RuntimeError("L'exécution créée est introuvable avant commit.")
        return result

    def finish_run(
        self,
        run_id: str,
        status: str,
        steps_results: list[dict[str, Any]],
        duration_ms: int,
    ) -> dict[str, Any] | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE workflow_runs SET status=?,steps_results=?,
                   finished_at=datetime('now'),duration_ms=? WHERE id=?""",
                (status, json.dumps(steps_results), duration_ms, run_id),
            )
            row = connection.execute(
                "SELECT * FROM workflow_runs WHERE id=?", (run_id,)
            ).fetchone()
        return self._parse_run(row)

    def list_runs(self, workflow_id: str, limit: int = 20) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM workflow_runs WHERE workflow_id=?
                   ORDER BY started_at DESC LIMIT ?""",
                (workflow_id, bounded_limit),
            ).fetchall()
        return [self._parse_run(row) for row in rows]


repository = WorkflowRepository()
create_workflow = repository.create_workflow
list_workflows = repository.list_workflows
get_workflow = repository.get_workflow
update_workflow = repository.update_workflow
delete_workflow = repository.delete_workflow
create_workflow_run = repository.create_run
finish_workflow_run = repository.finish_run
list_workflow_runs = repository.list_runs
