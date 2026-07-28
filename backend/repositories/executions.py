"""Persistance injectable et expurgée des exécutions d'outils."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict
from structured_logging import sanitize


ConnectionScope = Callable[[], AbstractContextManager]
_MAX_TRACE_ROWS = 5_000


def _decode_payload(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _parse_execution(row: dict | None, *, decode_payloads: bool) -> dict | None:
    if row is None:
        return None
    if decode_payloads:
        row["args"] = _decode_payload(row.get("args"))
        row["result"] = _decode_payload(row.get("result"))
    row["success"] = bool(row.get("success", 1))
    return row


class ExecutionRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS tool_executions (
                id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                args TEXT DEFAULT '{}',
                result TEXT,
                success INTEGER NOT NULL DEFAULT 1,
                duration_ms INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(tool_executions)"
            ).fetchall()
        }
        if "conversation_id" not in columns:
            connection.execute(
                "ALTER TABLE tool_executions ADD COLUMN conversation_id TEXT"
            )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_tool_executions_created
               ON tool_executions(created_at DESC)"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_tool_executions_tool
               ON tool_executions(tool_name, created_at DESC)"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_tool_executions_conversation
               ON tool_executions(conversation_id, created_at ASC)"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_tool_exec_success
               ON tool_executions(success, created_at DESC)"""
        )

    def log(
        self,
        tool_name: str,
        args: dict,
        result: dict,
        duration_ms: int,
        conversation_id: str | None = None,
    ) -> dict:
        execution_id = str(uuid.uuid4())
        succeeded = not (
            result.get("error") or result.get("success") is False
        )
        safe_args = sanitize(args, max_length=2_000)
        safe_result = sanitize(result, max_length=4_000)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO tool_executions (
                       id, tool_name, args, result, success, duration_ms,
                       conversation_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    execution_id,
                    tool_name,
                    json.dumps(safe_args, ensure_ascii=False),
                    json.dumps(safe_result, ensure_ascii=False),
                    int(succeeded),
                    duration_ms,
                    conversation_id,
                ),
            )
        return {
            "id": execution_id,
            "tool_name": tool_name,
            "success": succeeded,
            "duration_ms": duration_ms,
        }

    def conversation_trace(self, conversation_id: str) -> list[dict]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM tool_executions
                   WHERE conversation_id = ?
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (conversation_id, _MAX_TRACE_ROWS),
            ).fetchall()
        return [
            _parse_execution(row_to_dict(row), decode_payloads=False)
            for row in rows
        ]

    def list(
        self,
        tool_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        bounded_limit = min(max(int(limit), 1), 1_000)
        bounded_offset = min(max(int(offset), 0), 1_000_000)
        sql = "SELECT * FROM tool_executions WHERE 1=1"
        params: list[object] = []
        if tool_name:
            sql += " AND tool_name = ?"
            params.append(tool_name)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend((bounded_limit, bounded_offset))
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [
            _parse_execution(row_to_dict(row), decode_payloads=True)
            for row in rows
        ]

    def stats(self) -> dict:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            totals = connection.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS succeeded
                   FROM tool_executions"""
            ).fetchone()
            by_tool = connection.execute(
                """SELECT tool_name, COUNT(*) AS count
                   FROM tool_executions
                   GROUP BY tool_name
                   ORDER BY count DESC, tool_name ASC
                   LIMIT 10"""
            ).fetchall()
        total = int(totals["total"] or 0)
        succeeded = int(totals["succeeded"] or 0)
        return {
            "total": total,
            "success": succeeded,
            "failed": total - succeeded,
            "by_tool": [
                {"tool": row["tool_name"], "count": row["count"]}
                for row in by_tool
            ],
        }

    def reliability(
        self,
        min_calls: int = 3,
        days: int = 90,
        recent_days: int = 7,
    ) -> list[dict]:
        bounded_min_calls = min(max(int(min_calls), 1), 100_000)
        bounded_days = min(max(int(days), 1), 3_650)
        bounded_recent_days = min(max(int(recent_days), 1), bounded_days)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT tool_name,
                          COUNT(*) AS total,
                          SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END)
                              AS success_count,
                          SUM(CASE WHEN created_at >= datetime('now', ?)
                              THEN 1 ELSE 0 END) AS recent_total,
                          SUM(CASE WHEN created_at >= datetime('now', ?)
                              AND success = 1 THEN 1 ELSE 0 END)
                              AS recent_success_count
                   FROM tool_executions
                   WHERE created_at >= datetime('now', ?)
                   GROUP BY tool_name
                   HAVING total >= ?
                   ORDER BY
                     (1.0 * (total - success_count) / total) DESC,
                     total DESC""",
                (
                    f"-{bounded_recent_days} days",
                    f"-{bounded_recent_days} days",
                    f"-{bounded_days} days",
                    bounded_min_calls,
                ),
            ).fetchall()
        reliability: list[dict] = []
        for row in rows:
            total = row["total"]
            success_count = row["success_count"]
            failed = total - success_count
            recent_total = row["recent_total"] or 0
            recent_success = row["recent_success_count"] or 0
            recent_failed = recent_total - recent_success
            reliability.append(
                {
                    "tool": row["tool_name"],
                    "total_calls": total,
                    "success_count": success_count,
                    "failed_count": failed,
                    "failure_rate_pct": (
                        round(100.0 * failed / total, 1) if total else 0.0
                    ),
                    "recent_days": bounded_recent_days,
                    "recent_calls": recent_total,
                    "recent_failure_rate_pct": (
                        round(100.0 * recent_failed / recent_total, 1)
                        if recent_total
                        else None
                    ),
                    "likely_already_fixed": (
                        failed > 0
                        and recent_total >= bounded_min_calls
                        and recent_failed == 0
                    ),
                }
            )
        return reliability


repository = ExecutionRepository()
log_execution = repository.log
get_conversation_trace = repository.conversation_trace
list_executions = repository.list
get_execution_stats = repository.stats
get_tool_reliability = repository.reliability
