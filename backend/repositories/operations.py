"""Persistance injectable des pré/post-checks et preuves opérationnelles."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
_CHECK_UPDATE_COLUMNS = ("title", "status", "summary", "completed_at")


class OperationsRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS ops_checks (
                id TEXT PRIMARY KEY,
                intervention_id TEXT,
                check_type TEXT NOT NULL DEFAULT 'precheck'
                    CHECK(check_type IN ('precheck', 'postcheck')),
                title TEXT NOT NULL DEFAULT 'Checklist',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN (
                        'pending', 'running', 'passed', 'failed', 'partial'
                    )),
                summary TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS ops_check_items (
                id TEXT PRIMARY KEY,
                check_id TEXT NOT NULL,
                label TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                expected TEXT DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'info'
                    CHECK(severity IN ('info', 'warning', 'critical')),
                order_index INTEGER NOT NULL DEFAULT 0,
                auto_command TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (check_id)
                    REFERENCES ops_checks(id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS ops_check_results (
                id TEXT PRIMARY KEY,
                check_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'skipped'
                    CHECK(status IN ('ok', 'warning', 'failed', 'skipped')),
                actual_value TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                checked_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (check_id)
                    REFERENCES ops_checks(id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS ops_evidence (
                id TEXT PRIMARY KEY,
                check_id TEXT,
                item_id TEXT,
                result_id TEXT,
                intervention_id TEXT,
                evidence_type TEXT NOT NULL DEFAULT 'text'
                    CHECK(evidence_type IN (
                        'text', 'command', 'file_path', 'screenshot', 'log'
                    )),
                content TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ops_checks_interv "
            "ON ops_checks(intervention_id, check_type)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ops_items_check "
            "ON ops_check_items(check_id, order_index)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ops_results_check "
            "ON ops_check_results(check_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ops_evidence_interv "
            "ON ops_evidence(intervention_id)"
        )

    @staticmethod
    def _get_in_connection(connection, check_id: str) -> dict | None:
        row = connection.execute(
            "SELECT * FROM ops_checks WHERE id = ?",
            (check_id,),
        ).fetchone()
        if row is None:
            return None
        check = row_to_dict(row)
        items = [
            row_to_dict(item)
            for item in connection.execute(
                """SELECT * FROM ops_check_items
                   WHERE check_id = ?
                   ORDER BY order_index ASC, id ASC""",
                (check_id,),
            ).fetchall()
        ]
        results = [
            row_to_dict(result)
            for result in connection.execute(
                """SELECT * FROM ops_check_results
                   WHERE check_id = ?
                   ORDER BY checked_at ASC, id ASC""",
                (check_id,),
            ).fetchall()
        ]
        evidence = [
            row_to_dict(item)
            for item in connection.execute(
                """SELECT * FROM ops_evidence
                   WHERE check_id = ?
                   ORDER BY created_at ASC, id ASC""",
                (check_id,),
            ).fetchall()
        ]
        results_by_item = {result["item_id"]: result for result in results}
        for item in items:
            item["result"] = results_by_item.get(item["id"])
        check["items"] = items
        check["results"] = results
        check["evidence"] = evidence
        return check

    def check_create(self, data: dict) -> dict:
        check_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO ops_checks (
                       id, intervention_id, check_type, title, status, summary
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    check_id,
                    data.get("intervention_id"),
                    data.get("check_type", "precheck"),
                    data.get("title", "Checklist"),
                    data.get("status", "pending"),
                    data.get("summary", ""),
                ),
            )
            result = self._get_in_connection(connection, check_id)
        if result is None:
            raise RuntimeError("Le contrôle créé est introuvable avant commit.")
        return result

    def check_get(self, check_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            return self._get_in_connection(connection, check_id)

    def check_list(
        self,
        intervention_id: str | None = None,
        check_type: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM ops_checks WHERE 1=1"
        params: list[Any] = []
        if intervention_id:
            sql += " AND intervention_id = ?"
            params.append(intervention_id)
        if check_type:
            sql += " AND check_type = ?"
            params.append(check_type)
        sql += " ORDER BY created_at DESC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def check_update(self, check_id: str, data: dict) -> dict | None:
        columns: list[str] = []
        values: list[Any] = []
        for key in _CHECK_UPDATE_COLUMNS:
            if key in data:
                columns.append(f"{key} = ?")
                values.append(data[key])
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if columns:
                connection.execute(
                    f"UPDATE ops_checks SET {', '.join(columns)} WHERE id = ?",
                    (*values, check_id),
                )
            return self._get_in_connection(connection, check_id)

    def check_delete(self, check_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM ops_evidence WHERE check_id = ?",
                (check_id,),
            )
            connection.execute(
                "DELETE FROM ops_checks WHERE id = ?",
                (check_id,),
            )

    def item_create(self, check_id: str, data: dict) -> dict:
        item_id = str(uuid.uuid4())
        order_index = int(data.get("order_index", 0))
        if order_index < 0:
            raise ValueError("order_index ne peut pas être négatif.")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if (
                connection.execute(
                    "SELECT 1 FROM ops_checks WHERE id = ?",
                    (check_id,),
                ).fetchone()
                is None
            ):
                raise ValueError("Le contrôle parent est introuvable.")
            connection.execute(
                """INSERT INTO ops_check_items (
                       id, check_id, label, category, expected,
                       severity, order_index, auto_command
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    check_id,
                    data.get("label", ""),
                    data.get("category", "general"),
                    data.get("expected", ""),
                    data.get("severity", "info"),
                    order_index,
                    data.get("auto_command", ""),
                ),
            )
            row = connection.execute(
                "SELECT * FROM ops_check_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("Le point créé est introuvable avant commit.")
        return result

    def result_set(
        self,
        check_id: str,
        item_id: str,
        data: dict,
    ) -> dict:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            item = connection.execute(
                """SELECT id FROM ops_check_items
                   WHERE id = ? AND check_id = ?""",
                (item_id, check_id),
            ).fetchone()
            if item is None:
                raise ValueError(
                    "Le point de contrôle n'appartient pas à cette checklist."
                )
            existing = connection.execute(
                """SELECT id FROM ops_check_results
                   WHERE check_id = ? AND item_id = ?
                   ORDER BY checked_at DESC, id ASC
                   LIMIT 1""",
                (check_id, item_id),
            ).fetchone()
            if existing:
                result_id = existing["id"]
                connection.execute(
                    """UPDATE ops_check_results
                       SET status = ?, actual_value = ?, notes = ?,
                           checked_at = datetime('now')
                       WHERE id = ?""",
                    (
                        data.get("status", "skipped"),
                        data.get("actual_value", ""),
                        data.get("notes", ""),
                        result_id,
                    ),
                )
            else:
                result_id = str(uuid.uuid4())
                connection.execute(
                    """INSERT INTO ops_check_results (
                           id, check_id, item_id, status, actual_value, notes
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        result_id,
                        check_id,
                        item_id,
                        data.get("status", "skipped"),
                        data.get("actual_value", ""),
                        data.get("notes", ""),
                    ),
                )
            row = connection.execute(
                "SELECT * FROM ops_check_results WHERE id = ?",
                (result_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("Le résultat est introuvable avant commit.")
        return result

    def evidence_create(self, data: dict) -> dict:
        evidence_id = str(uuid.uuid4())
        check_id = data.get("check_id")
        item_id = data.get("item_id")
        result_id = data.get("result_id")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if check_id and (
                connection.execute(
                    "SELECT 1 FROM ops_checks WHERE id = ?",
                    (check_id,),
                ).fetchone()
                is None
            ):
                raise ValueError("Le contrôle lié à la preuve est introuvable.")
            if item_id and (
                connection.execute(
                    """SELECT 1 FROM ops_check_items
                       WHERE id = ? AND (? IS NULL OR check_id = ?)""",
                    (item_id, check_id, check_id),
                ).fetchone()
                is None
            ):
                raise ValueError("Le point lié à la preuve est introuvable.")
            if result_id and (
                connection.execute(
                    """SELECT 1 FROM ops_check_results
                       WHERE id = ? AND (? IS NULL OR check_id = ?)
                         AND (? IS NULL OR item_id = ?)""",
                    (
                        result_id,
                        check_id,
                        check_id,
                        item_id,
                        item_id,
                    ),
                ).fetchone()
                is None
            ):
                raise ValueError("Le résultat lié à la preuve est introuvable.")
            connection.execute(
                """INSERT INTO ops_evidence (
                       id, check_id, item_id, result_id, intervention_id,
                       evidence_type, content
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    evidence_id,
                    check_id,
                    item_id,
                    result_id,
                    data.get("intervention_id"),
                    data.get("evidence_type", "text"),
                    data.get("content", ""),
                ),
            )
            row = connection.execute(
                "SELECT * FROM ops_evidence WHERE id = ?",
                (evidence_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("La preuve créée est introuvable avant commit.")
        return result

    def evidence_list(
        self,
        intervention_id: str | None = None,
        check_id: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM ops_evidence WHERE 1=1"
        params: list[Any] = []
        if intervention_id:
            sql += " AND intervention_id = ?"
            params.append(intervention_id)
        if check_id:
            sql += " AND check_id = ?"
            params.append(check_id)
        sql += " ORDER BY created_at DESC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]


repository = OperationsRepository()
ops_check_create = repository.check_create
ops_check_get = repository.check_get
ops_check_list = repository.check_list
ops_check_update = repository.check_update
ops_check_delete = repository.check_delete
ops_item_create = repository.item_create
ops_result_set = repository.result_set
ops_evidence_create = repository.evidence_create
ops_evidence_list = repository.evidence_list
