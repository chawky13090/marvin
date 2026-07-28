"""Persistance injectable des tâches planifiées Marvin."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
_MUTABLE_COLUMNS = (
    "name",
    "schedule",
    "tool_name",
    "next_run",
    "last_run",
    "last_result",
)


def _parse_cron(row: dict | None) -> dict | None:
    if row is None:
        return None
    parsed = dict(row)
    if parsed.get("args") and isinstance(parsed["args"], str):
        try:
            decoded = json.loads(parsed["args"])
            parsed["args"] = decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            parsed["args"] = {}
    parsed["enabled"] = bool(parsed.get("enabled", 1))
    return parsed


class CronJobRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS cron_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args TEXT DEFAULT '{}',
                schedule TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run TEXT,
                next_run TEXT,
                run_count INTEGER NOT NULL DEFAULT 0,
                last_result TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_cron_enabled_next
               ON cron_jobs(enabled, next_run)"""
        )

    def create(
        self,
        name: str,
        tool_name: str,
        args: dict,
        schedule: str,
    ) -> dict:
        if not isinstance(args, dict):
            raise TypeError("Les arguments cron doivent être un objet JSON.")
        job_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO cron_jobs (
                       id, name, tool_name, args, schedule
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    job_id,
                    str(name),
                    str(tool_name),
                    json.dumps(args, ensure_ascii=False),
                    str(schedule),
                ),
            )
            row = connection.execute(
                "SELECT * FROM cron_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        result = _parse_cron(row_to_dict(row))
        if result is None:
            raise RuntimeError("La tâche cron créée est introuvable avant commit.")
        return result

    def list(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM cron_jobs"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name ASC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql).fetchall()
        return [
            parsed
            for row in rows
            if (parsed := _parse_cron(row_to_dict(row))) is not None
        ]

    def update(self, job_id: str, updates: dict) -> dict | None:
        if not isinstance(updates, dict):
            raise TypeError("Les mises à jour cron doivent être un objet.")
        fields: list[str] = []
        values: list[Any] = []
        for key in _MUTABLE_COLUMNS:
            if key in updates:
                fields.append(f"{key} = ?")
                values.append(updates[key])
        if "args" in updates:
            if not isinstance(updates["args"], dict):
                raise TypeError("Les arguments cron doivent être un objet JSON.")
            fields.append("args = ?")
            values.append(json.dumps(updates["args"], ensure_ascii=False))
        if "enabled" in updates:
            fields.append("enabled = ?")
            values.append(1 if updates["enabled"] else 0)
        if "run_count" in updates:
            fields.append("run_count = run_count + 1")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if fields:
                fields.append("updated_at = datetime('now')")
                connection.execute(
                    f"UPDATE cron_jobs SET {', '.join(fields)} WHERE id = ?",
                    (*values, job_id),
                )
            row = connection.execute(
                "SELECT * FROM cron_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return _parse_cron(row_to_dict(row))

    def get(self, job_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM cron_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return _parse_cron(row_to_dict(row))

    def delete(self, job_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))


repository = CronJobRepository()
create_cron_job = repository.create
list_cron_jobs = repository.list
update_cron_job = repository.update
get_cron_job = repository.get
delete_cron_job = repository.delete
