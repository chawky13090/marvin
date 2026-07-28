"""Persistance injectable des analyses de commandes et approbations."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict
from repositories.command_safety_rules import DEFAULT_COMMAND_RISK_RULES


ConnectionScope = Callable[[], AbstractContextManager]
_PLATFORMS = {
    "powershell",
    "cmd",
    "bash",
    "linux",
    "proxmox",
    "cisco",
    "firewall",
    "unknown",
}
_RISKS = {"safe", "medium", "high", "critical", "blocked"}
_DECISIONS = {"approved", "rejected"}


def _enum(value: Any, *, field: str, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(
            f"{field} invalide; valeurs autorisées: {', '.join(sorted(allowed))}."
        )
    return normalized


class CommandSafetyRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS command_reviews (
                id TEXT PRIMARY KEY,
                intervention_id TEXT,
                command TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'unknown'
                    CHECK(platform IN (
                        'powershell','cmd','bash','linux','proxmox',
                        'cisco','firewall','unknown'
                    )),
                risk_level TEXT NOT NULL DEFAULT 'safe'
                    CHECK(risk_level IN (
                        'safe','medium','high','critical','blocked'
                    )),
                risk_explanation TEXT DEFAULT '',
                safer_alternative TEXT DEFAULT '',
                requires_approval INTEGER NOT NULL DEFAULT 0,
                matched_rule TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS command_risk_rules (
                id TEXT PRIMARY KEY,
                pattern TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'unknown',
                risk_level TEXT NOT NULL DEFAULT 'medium',
                explanation TEXT DEFAULT '',
                safer_alternative TEXT DEFAULT '',
                is_builtin INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS approval_requests (
                id TEXT PRIMARY KEY,
                command_review_id TEXT,
                command TEXT NOT NULL,
                requested_by TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                approver TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                decided_at TEXT
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_cmd_reviews_interv "
            "ON command_reviews(intervention_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_cmd_reviews_risk "
            "ON command_reviews(risk_level)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_approval_status "
            "ON approval_requests(status)"
        )
        count = connection.execute(
            "SELECT COUNT(*) FROM command_risk_rules"
        ).fetchone()[0]
        if count == 0:
            for pattern, platform, risk, explanation, alternative in (
                DEFAULT_COMMAND_RISK_RULES
            ):
                connection.execute(
                    """INSERT INTO command_risk_rules (
                           id, pattern, platform, risk_level, explanation,
                           safer_alternative, is_builtin
                       ) VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    (
                        str(uuid.uuid4()),
                        pattern,
                        platform,
                        risk,
                        explanation,
                        alternative,
                    ),
                )

    def rules_list(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM command_risk_rules"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY created_at ASC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql).fetchall()
        return [row_to_dict(row) for row in rows]

    def review_create(self, data: dict) -> dict:
        command = str(data.get("command") or "").strip()
        if not command:
            raise ValueError("command est requis.")
        platform = _enum(
            data.get("platform", "unknown"),
            field="platform",
            allowed=_PLATFORMS,
        )
        risk_level = _enum(
            data.get("risk_level", "safe"),
            field="risk_level",
            allowed=_RISKS,
        )
        review_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO command_reviews (
                       id, intervention_id, command, platform, risk_level,
                       risk_explanation, safer_alternative,
                       requires_approval, matched_rule
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id,
                    data.get("intervention_id"),
                    command,
                    platform,
                    risk_level,
                    data.get("risk_explanation", ""),
                    data.get("safer_alternative", ""),
                    1 if data.get("requires_approval") else 0,
                    data.get("matched_rule", ""),
                ),
            )
            row = connection.execute(
                "SELECT * FROM command_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError(
                "L'analyse créée est introuvable avant le commit."
            )
        return result

    def review_list(
        self,
        intervention_id: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        bounded_limit = min(max(int(limit), 1), 1_000)
        sql = "SELECT * FROM command_reviews WHERE 1=1"
        params: list[Any] = []
        if intervention_id:
            sql += " AND intervention_id = ?"
            params.append(intervention_id)
        if risk_level:
            sql += " AND risk_level = ?"
            params.append(
                _enum(risk_level, field="risk_level", allowed=_RISKS)
            )
        sql += " ORDER BY created_at DESC, id ASC LIMIT ?"
        params.append(bounded_limit)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def approval_create(self, data: dict) -> dict:
        review_id = str(data.get("command_review_id") or "").strip() or None
        command = str(data.get("command") or "").strip()
        approval_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if review_id:
                review = connection.execute(
                    "SELECT command FROM command_reviews WHERE id = ?",
                    (review_id,),
                ).fetchone()
                if review is None:
                    raise ValueError(
                        "command_review_id ne référence aucune analyse."
                    )
                reviewed_command = str(review["command"])
                if command and command != reviewed_command:
                    raise ValueError(
                        "La commande ne correspond pas à l'analyse référencée."
                    )
                command = reviewed_command
            if not command:
                raise ValueError("command est requis.")
            connection.execute(
                """INSERT INTO approval_requests (
                       id, command_review_id, command, requested_by,
                       status, reason
                   ) VALUES (?, ?, ?, ?, 'pending', ?)""",
                (
                    approval_id,
                    review_id,
                    command,
                    data.get("requested_by", ""),
                    data.get("reason", ""),
                ),
            )
            row = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError(
                "La demande créée est introuvable avant le commit."
            )
        return result

    def approval_list(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM approval_requests"
        params: tuple[Any, ...] = ()
        if status:
            normalized = _enum(
                status,
                field="status",
                allowed={"pending", *_DECISIONS},
            )
            sql += " WHERE status = ?"
            params = (normalized,)
        sql += " ORDER BY created_at DESC, id ASC LIMIT 1000"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def approval_decide(
        self,
        approval_id: str,
        status: str,
        approver: str = "",
        reason: str = "",
    ) -> dict | None:
        decision = _enum(status, field="status", allowed=_DECISIONS)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            current = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
            if current is None:
                return None
            if current["status"] == decision:
                return row_to_dict(current)
            if current["status"] != "pending":
                raise ValueError(
                    "Une décision finale contradictoire ne peut pas être remplacée."
                )
            connection.execute(
                """UPDATE approval_requests
                   SET status = ?, approver = ?, reason = ?,
                       decided_at = datetime('now')
                   WHERE id = ? AND status = 'pending'""",
                (decision, approver, reason, approval_id),
            )
            row = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
            return row_to_dict(row)


repository = CommandSafetyRepository()
cmd_rules_list = repository.rules_list
cmd_review_create = repository.review_create
cmd_review_list = repository.review_list
approval_create = repository.approval_create
approval_list = repository.approval_list
approval_decide = repository.approval_decide
