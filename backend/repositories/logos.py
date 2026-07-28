"""Persistance injectable du catalogue de logos locaux."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


class LogoRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS logos (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prompt TEXT,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )

    def create(self, name: str, prompt: str, path: str) -> dict:
        logo_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "INSERT INTO logos (id, name, prompt, path) VALUES (?, ?, ?, ?)",
                (logo_id, name, prompt, path),
            )
            row = connection.execute(
                "SELECT * FROM logos WHERE id = ?",
                (logo_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("Le logo créé est introuvable avant commit.")
        return result

    def list(self, limit: int = 100) -> list[dict]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                "SELECT * FROM logos ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row_to_dict(row) for row in rows]


repository = LogoRepository()
create_logo = repository.create
list_logos = repository.list
