"""Persistance injectable des notes personnelles de Marvin."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


def _parse_note(row: dict | None) -> dict | None:
    if row is None:
        return None
    if row.get("tags") and isinstance(row["tags"], str):
        try:
            row["tags"] = json.loads(row["tags"])
        except json.JSONDecodeError:
            row["tags"] = []
    row["pinned"] = bool(row.get("pinned", 0))
    return row


class NoteRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    def create(
        self,
        title: str,
        content: str = "",
        tags: list | None = None,
        pinned: bool = False,
    ) -> dict:
        note_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            connection.execute(
                """INSERT INTO notes (id, title, content, tags, pinned)
                   VALUES (?, ?, ?, ?, ?)""",
                (note_id, title, content, json.dumps(tags or []), int(pinned)),
            )
            row = connection.execute(
                "SELECT * FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        result = _parse_note(row_to_dict(row))
        if result is None:
            raise RuntimeError("La note créée est introuvable avant commit.")
        return result

    def get(self, note_id: str) -> dict | None:
        with self._connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        return _parse_note(row_to_dict(row))

    def list(
        self,
        search: str | None = None,
        pinned: bool | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = "SELECT * FROM notes WHERE 1=1"
        params: list[object] = []
        if search:
            sql += " AND (title LIKE ? OR content LIKE ?)"
            params.extend((f"%{search}%", f"%{search}%"))
        if pinned is not None:
            sql += " AND pinned = ?"
            params.append(int(pinned))
        sql += " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connection_scope() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_parse_note(row_to_dict(row)) for row in rows]

    def update(self, note_id: str, updates: dict) -> dict | None:
        fields: list[str] = []
        values: list[object] = []
        for key in ("title", "content"):
            if key in updates:
                fields.append(f"{key} = ?")
                values.append(updates[key])
        if "tags" in updates:
            fields.append("tags = ?")
            values.append(json.dumps(updates["tags"]))
        if "pinned" in updates:
            fields.append("pinned = ?")
            values.append(int(bool(updates["pinned"])))
        if not fields:
            return self.get(note_id)
        fields.append("updated_at = datetime('now')")
        values.append(note_id)
        with self._connection_scope() as connection:
            connection.execute(
                f"UPDATE notes SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            row = connection.execute(
                "SELECT * FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        return _parse_note(row_to_dict(row))

    def delete(self, note_id: str) -> None:
        with self._connection_scope() as connection:
            connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def restore(self, note: dict) -> dict:
        """Restaure exactement une pré-image possédée par l'appelant."""
        required = {"id", "title", "content", "created_at", "updated_at"}
        if not required.issubset(note):
            raise ValueError("Pré-image de note incomplète.")
        with self._connection_scope() as connection:
            connection.execute(
                """INSERT INTO notes (id, title, content, tags, pinned, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     title = excluded.title,
                     content = excluded.content,
                     tags = excluded.tags,
                     pinned = excluded.pinned,
                     created_at = excluded.created_at,
                     updated_at = excluded.updated_at""",
                (
                    str(note["id"]),
                    str(note["title"]),
                    str(note.get("content") or ""),
                    json.dumps(note.get("tags") or []),
                    int(bool(note.get("pinned"))),
                    str(note["created_at"]),
                    str(note["updated_at"]),
                ),
            )
            row = connection.execute(
                "SELECT * FROM notes WHERE id = ?",
                (str(note["id"]),),
            ).fetchone()
        restored = _parse_note(row_to_dict(row))
        if restored is None:
            raise RuntimeError("La pré-image de note restaurée est introuvable.")
        return restored


repository = NoteRepository()
create_note = repository.create
get_note = repository.get
list_notes = repository.list
update_note = repository.update
delete_note = repository.delete
restore_note = repository.restore
