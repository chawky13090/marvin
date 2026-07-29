"""Checkpoints SQLite des exécutions de l'orchestrateur LLM natif."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db


ConnectionScope = Callable[[], AbstractContextManager]


class AgentRunConflict(RuntimeError):
    pass


class AgentRunRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    def ensure_schema(self) -> None:
        with self._connection_scope() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS agent_runs (
                       run_id TEXT PRIMARY KEY,
                       conversation_id TEXT,
                       request_id TEXT,
                       status TEXT NOT NULL,
                       state_json TEXT NOT NULL,
                       version INTEGER NOT NULL DEFAULT 1,
                       created_at TEXT NOT NULL DEFAULT (datetime('now')),
                       updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                   )"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation
                   ON agent_runs(conversation_id, updated_at DESC)"""
            )

    def create(
        self,
        run_id: str,
        *,
        conversation_id: str,
        request_id: str,
        status: str,
        state: dict[str, Any],
    ) -> int:
        serialized = self._serialize(state)
        with self._connection_scope() as connection:
            connection.execute(
                """INSERT INTO agent_runs(
                       run_id, conversation_id, request_id, status, state_json, version
                   ) VALUES (?, ?, ?, ?, ?, 1)""",
                (
                    self._identifier(run_id, "run_id"),
                    self._identifier(conversation_id, "conversation_id", optional=True),
                    self._identifier(request_id, "request_id", optional=True),
                    self._status(status),
                    serialized,
                ),
            )
        return 1

    def load(self, run_id: str) -> dict[str, Any] | None:
        with self._connection_scope() as connection:
            row = connection.execute(
                """SELECT run_id, conversation_id, request_id, status,
                          state_json, version, created_at, updated_at
                   FROM agent_runs WHERE run_id = ?""",
                (self._identifier(run_id, "run_id"),),
            ).fetchone()
        if row is None:
            return None
        try:
            state = json.loads(row["state_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Checkpoint agent corrompu.") from exc
        if not isinstance(state, dict):
            raise ValueError("Checkpoint agent invalide.")
        return {
            "run_id": row["run_id"],
            "conversation_id": row["conversation_id"] or "",
            "request_id": row["request_id"] or "",
            "status": row["status"],
            "state": state,
            "version": int(row["version"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save(
        self,
        run_id: str,
        *,
        expected_version: int,
        status: str,
        state: dict[str, Any],
    ) -> int:
        if expected_version < 1:
            raise ValueError("Version de checkpoint invalide.")
        serialized = self._serialize(state)
        with self._connection_scope() as connection:
            cursor = connection.execute(
                """UPDATE agent_runs
                   SET status = ?, state_json = ?, version = version + 1,
                       updated_at = datetime('now')
                   WHERE run_id = ? AND version = ?""",
                (
                    self._status(status),
                    serialized,
                    self._identifier(run_id, "run_id"),
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentRunConflict("Checkpoint modifié par une autre exécution.")
        return expected_version + 1

    def delete(self, run_id: str) -> bool:
        with self._connection_scope() as connection:
            cursor = connection.execute(
                "DELETE FROM agent_runs WHERE run_id = ?",
                (self._identifier(run_id, "run_id"),),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _identifier(value: str, field: str, *, optional: bool = False) -> str:
        normalized = str(value or "").strip()
        if optional and not normalized:
            return ""
        if not normalized or len(normalized) > 160:
            raise ValueError(f"{field} invalide.")
        return normalized

    @staticmethod
    def _status(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {
            "running",
            "pending_approval",
            "completed",
            "stopped",
            "failed",
        }:
            raise ValueError("Statut de run invalide.")
        return normalized

    @staticmethod
    def _serialize(state: dict[str, Any]) -> str:
        if not isinstance(state, dict):
            raise ValueError("État agent invalide.")
        try:
            serialized = json.dumps(
                state,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("État agent non sérialisable.") from exc
        if len(serialized.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("Checkpoint agent supérieur à 2 Mio.")
        return serialized

