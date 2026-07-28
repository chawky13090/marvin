"""Persistance injectable des modèles d'appels d'outils."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


def _parse_template(row: dict | None) -> dict | None:
    if row is None:
        return None
    parsed = dict(row)
    if parsed.get("args") and isinstance(parsed["args"], str):
        try:
            decoded = json.loads(parsed["args"])
            parsed["args"] = decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            parsed["args"] = {}
    return parsed


class ToolTemplateRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS tool_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args TEXT DEFAULT '{}',
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_tool_templates_lookup
               ON tool_templates(tool_name, category, name)"""
        )

    def save(
        self,
        name: str,
        tool_name: str,
        args: dict,
        description: str = "",
        category: str = "general",
    ) -> dict:
        if not isinstance(args, dict):
            raise TypeError("Les arguments du modèle doivent être un objet JSON.")
        template_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO tool_templates (
                       id, name, tool_name, args, description, category
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    template_id,
                    str(name),
                    str(tool_name),
                    json.dumps(args, ensure_ascii=False),
                    str(description),
                    str(category),
                ),
            )
            row = connection.execute(
                "SELECT * FROM tool_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        result = _parse_template(row_to_dict(row))
        if result is None:
            raise RuntimeError("Le modèle créé est introuvable avant commit.")
        return result

    def list(
        self,
        tool_name: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM tool_templates WHERE 1=1"
        params: list[Any] = []
        if tool_name:
            sql += " AND tool_name = ?"
            params.append(tool_name)
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY name ASC, id ASC"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [
            parsed
            for row in rows
            if (parsed := _parse_template(row_to_dict(row))) is not None
        ]

    def get(self, template_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM tool_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        return _parse_template(row_to_dict(row))

    def delete(self, template_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM tool_templates WHERE id = ?",
                (template_id,),
            )


repository = ToolTemplateRepository()
save_template = repository.save
list_templates = repository.list
get_template = repository.get
delete_template = repository.delete
