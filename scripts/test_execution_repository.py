"""Régressions SQLite du repository d'exécutions et de fiabilité."""

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
from repositories.executions import ExecutionRepository
from rollback_execution_telemetry_schema import TELEMETRY_COLUMNS, rollback


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "executions.db"
        repository = ExecutionRepository(connection_scope=lambda: db(path))

        with patch("repositories.executions.uuid.uuid4", return_value="execution-1"):
            first = repository.log(
                "net_ping",
                {
                    "host": "127.0.0.1",
                    "password": "interdit",
                    "content": "document confidentiel",
                },
                {"success": True, "token": "interdit", "message": "OK"},
                42,
                conversation_id="conversation-1",
                request_id="request-12345678",
                tool_call_id="tool-call-1",
                execution_context={
                    "app_version": "2.659.0",
                    "model_name": "test:model",
                    "runtime_mode": "eco",
                    "profile_name": "agent",
                    "selector_version": "kls-main/v1",
                    "candidate_count": 18,
                    "candidate_set_sha256": "a" * 64,
                },
                execution_source="agent_chat",
                canonicalized_from="legacy_net_ping",
            )
        assert first["success"] is True

        with patch("repositories.executions.uuid.uuid4", return_value="execution-2"):
            repository.log(
                "net_ping",
                {"host": "127.0.0.2"},
                {"error": "timeout"},
                100,
                conversation_id="conversation-1",
            )
        with patch("repositories.executions.uuid.uuid4", return_value="execution-3"):
            repository.log(
                "net_ping",
                {"host": "127.0.0.3"},
                {"success": True},
                10,
                conversation_id="conversation-2",
            )

        rows = repository.list(tool_name="net_ping", limit=99)
        by_id = {row["id"]: row for row in rows}
        assert by_id["execution-1"]["args"]["password"] == "***"
        assert by_id["execution-1"]["args"]["content"]["redacted"] is True
        assert by_id["execution-1"]["result"]["token"] == "***"
        assert by_id["execution-2"]["success"] is False
        assert by_id["execution-1"]["tool_call_id"] == "tool-call-1"
        assert by_id["execution-1"]["candidate_count"] == 18
        assert by_id["execution-1"]["candidate_set_sha256"] == "a" * 64
        assert by_id["execution-1"]["execution_source"] == "agent_chat"
        assert "test:model" not in str(by_id["execution-2"])

        trace = repository.conversation_trace("conversation-1")
        assert {row["id"] for row in trace} == {"execution-1", "execution-2"}
        assert "interdit" not in str(trace)
        request_trace = repository.request_trace("request-12345678")
        assert [row["id"] for row in request_trace] == ["execution-1"]
        assert request_trace[0]["request_id"] == "request-12345678"
        assert repository.list(limit=0)
        assert repository.list(limit=10, offset=-10)

        with db(path) as connection:
            connection.execute(
                """UPDATE tool_executions
                   SET created_at = datetime('now', '-30 days')
                   WHERE id = ?""",
                ("execution-2",),
            )
            connection.execute(
                """INSERT INTO tool_executions (
                       id, tool_name, args, result, success, duration_ms
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                ("corrupt", "other", "{invalid", "{invalid", 0, 1),
            )
        corrupt = repository.list(tool_name="other")[0]
        assert corrupt["args"] == {} and corrupt["result"] == {}

        stats = repository.stats()
        assert stats["total"] == 4
        assert stats["success"] == 2 and stats["failed"] == 2
        reliability = repository.reliability(
            min_calls=2,
            days=90,
            recent_days=7,
        )
        ping = next(row for row in reliability if row["tool"] == "net_ping")
        assert ping["total_calls"] == 3 and ping["failed_count"] == 1
        assert ping["recent_calls"] == 2
        assert ping["recent_failure_rate_pct"] == 0.0
        assert ping["likely_already_fixed"] is True

        with patch("repositories.executions.uuid.uuid4", return_value="execution-1"):
            try:
                repository.log("net_ping", {}, {"success": True}, 1)
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Une clé d'exécution dupliquée doit annuler le log.")
        assert repository.stats()["total"] == 4

        with patch("repositories.executions.uuid.uuid4", return_value="execution-5"):
            try:
                repository.log(
                    "net_ping", {}, {"success": True}, 1,
                    tool_call_id="tool-call-1",
                )
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Un tool_call_id ne doit identifier qu'une execution.")
        assert repository.stats()["total"] == 4

        legacy_path = root / "legacy-executions.db"
        with db(legacy_path) as connection:
            connection.execute(
                """CREATE TABLE tool_executions (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    args TEXT DEFAULT '{}',
                    result TEXT,
                    success INTEGER NOT NULL DEFAULT 1,
                    duration_ms INTEGER,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
        legacy = ExecutionRepository(connection_scope=lambda: db(legacy_path))
        assert legacy.stats()["total"] == 0
        with db(legacy_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(tool_executions)"
                ).fetchall()
            }
        assert {
            "conversation_id", "request_id", "tool_call_id", "app_version",
            "model_name", "runtime_mode", "profile_name", "selector_version",
            "candidate_count", "candidate_set_sha256", "execution_source",
            "canonicalized_from",
        } <= columns

        rollback_result = rollback(legacy_path, confirmed=True)
        assert rollback_result["integrity_check"] == "ok"
        assert Path(str(rollback_result["backup"])).is_file()
        with db(legacy_path) as connection:
            rolled_back_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(tool_executions)"
                ).fetchall()
            }
        assert not (set(TELEMETRY_COLUMNS) & rolled_back_columns)

    import database
    from repositories import executions

    expected = {
        "log_execution": executions.log_execution,
        "get_conversation_trace": executions.get_conversation_trace,
        "get_request_trace": executions.get_request_trace,
        "list_executions": executions.list_executions,
        "get_execution_stats": executions.get_execution_stats,
        "get_tool_reliability": executions.get_tool_reliability,
    }
    for name, function in expected.items():
        assert getattr(database, name) is function, name

    print(
        "Execution Repository OK - corrélation, expurgation, statistiques, "
        "fiabilité, migration, bornes, rollback et façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
