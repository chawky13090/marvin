"""Persistance injectable des captures documentaires."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


class ScreenshotRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS screenshots (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                path TEXT NOT NULL,
                caption TEXT,
                ocr_text TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )

    def create(
        self,
        conversation_id: str | None,
        path: str,
        caption: str = "",
        ocr_text: str = "",
    ) -> dict:
        screenshot_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO screenshots (
                       id, conversation_id, path, caption, ocr_text
                   ) VALUES (?, ?, ?, ?, ?)""",
                (screenshot_id, conversation_id, path, caption, ocr_text),
            )
            row = connection.execute(
                "SELECT * FROM screenshots WHERE id = ?",
                (screenshot_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("La capture créée est introuvable avant commit.")
        return result

    def list(
        self,
        conversation_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if conversation_id:
                rows = connection.execute(
                    """SELECT * FROM screenshots
                       WHERE conversation_id = ?
                       ORDER BY created_at ASC LIMIT ?""",
                    (conversation_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM screenshots
                       ORDER BY created_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [row_to_dict(row) for row in rows]


repository = ScreenshotRepository()
create_screenshot = repository.create
list_screenshots = repository.list
