"""Persistance des conversations et messages, independante de FastAPI."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


class ConversationRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def _ensure_pinned_column(connection) -> None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(conversations)")}
        if "pinned" not in columns:
            connection.execute(
                "ALTER TABLE conversations ADD COLUMN pinned INTEGER DEFAULT 0"
            )

    def create_conversation(self, title: str = "Nouvelle conversation") -> dict:
        conversation_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self._ensure_pinned_column(connection)
            connection.execute(
                "INSERT INTO conversations (id, title) VALUES (?, ?)",
                (conversation_id, title),
            )
        result = self.get_conversation(conversation_id)
        if result is None:
            raise RuntimeError("La conversation creee est introuvable apres commit.")
        return result

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self._ensure_pinned_column(connection)
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return row_to_dict(row)

    def list_conversations(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._connection_scope() as connection:
            self._ensure_pinned_column(connection)
            rows = connection.execute(
                """SELECT * FROM conversations
                   ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def set_conversation_pinned(self, conversation_id: str, pinned: bool) -> None:
        with self._connection_scope() as connection:
            self._ensure_pinned_column(connection)
            connection.execute(
                "UPDATE conversations SET pinned = ? WHERE id = ?",
                (1 if pinned else 0, conversation_id),
            )

    def search_conversations(self, query: str, limit: int = 50) -> list[dict]:
        pattern = f"%{query.strip()}%"
        with self._connection_scope() as connection:
            self._ensure_pinned_column(connection)
            rows = connection.execute(
                """SELECT DISTINCT c.* FROM conversations c
                   LEFT JOIN messages m ON m.conversation_id = c.id
                   WHERE c.title LIKE ? OR m.content LIKE ?
                   ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ?""",
                (pattern, pattern, limit),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        with self._connection_scope() as connection:
            connection.execute(
                "UPDATE conversations SET title = ?, updated_at = datetime('now') WHERE id = ?",
                (title, conversation_id),
            )

    def upgrade_conversation_title_silent(
        self, conversation_id: str, title: str
    ) -> None:
        with self._connection_scope() as connection:
            connection.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, conversation_id),
            )

    def update_conversation_project(
        self, conversation_id: str, project_id: str | None
    ) -> None:
        with self._connection_scope() as connection:
            connection.execute(
                "UPDATE conversations SET project_id = ?, updated_at = datetime('now') WHERE id = ?",
                (project_id, conversation_id),
            )

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connection_scope() as connection:
            connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def create_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        tool_calls: list | None = None,
        tool_results: list | None = None,
        client_request_id: str | None = None,
    ) -> dict:
        message_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(messages)")
            }
            supports_request_id = "client_request_id" in columns
            if client_request_id and supports_request_id:
                existing = connection.execute(
                    """SELECT * FROM messages
                       WHERE conversation_id = ? AND client_request_id = ?""",
                    (conversation_id, client_request_id),
                ).fetchone()
                if existing is not None:
                    parsed = self._parse_message(row_to_dict(existing))
                    if parsed and parsed.get("role") == role and parsed.get("content") == content:
                        return parsed
                    raise ValueError(
                        "Le client_request_id existe deja avec un contenu different."
                    )

            if supports_request_id:
                connection.execute(
                    """INSERT INTO messages
                       (id, conversation_id, role, content, tool_calls, tool_results, client_request_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message_id,
                        conversation_id,
                        role,
                        content,
                        json.dumps(tool_calls) if tool_calls else None,
                        json.dumps(tool_results) if tool_results else None,
                        client_request_id,
                    ),
                )
            else:
                connection.execute(
                    """INSERT INTO messages
                       (id, conversation_id, role, content, tool_calls, tool_results)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        message_id,
                        conversation_id,
                        role,
                        content,
                        json.dumps(tool_calls) if tool_calls else None,
                        json.dumps(tool_results) if tool_results else None,
                    ),
                )
            connection.execute(
                "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                (conversation_id,),
            )
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        result = self._parse_message(row_to_dict(row))
        if result is None:
            raise RuntimeError("Le message cree est introuvable avant commit.")
        return result

    def get_messages_by_conversation(
        self, conversation_id: str, limit: int = 100
    ) -> list[dict]:
        with self._connection_scope() as connection:
            rows = connection.execute(
                """SELECT * FROM messages WHERE conversation_id = ?
                   ORDER BY created_at ASC, rowid ASC LIMIT ?""",
                (conversation_id, limit),
            ).fetchall()
        return [self._parse_message(row_to_dict(row)) for row in rows]

    def get_recent_user_messages(self, limit: int = 120) -> list[str]:
        with self._connection_scope() as connection:
            rows = connection.execute(
                """SELECT content FROM messages WHERE role = 'user'
                   AND content IS NOT NULL AND length(content) > 6
                   ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        output: list[str] = []
        seen: set[str] = set()
        for row in rows:
            content = str(row["content"] or "").strip()
            key = content.lower()[:80]
            if content and key not in seen:
                seen.add(key)
                output.append(content[:300])
        return output

    @staticmethod
    def _parse_message(row: dict | None) -> dict | None:
        if row is None:
            return None
        for field in ("tool_calls", "tool_results"):
            if row.get(field) and isinstance(row[field], str):
                try:
                    row[field] = json.loads(row[field])
                except (json.JSONDecodeError, TypeError):
                    row[field] = None
        return row


repository = ConversationRepository()

create_conversation = repository.create_conversation
get_conversation = repository.get_conversation
list_conversations = repository.list_conversations
set_conversation_pinned = repository.set_conversation_pinned
search_conversations = repository.search_conversations
update_conversation_title = repository.update_conversation_title
upgrade_conversation_title_silent = repository.upgrade_conversation_title_silent
update_conversation_project = repository.update_conversation_project
delete_conversation = repository.delete_conversation
create_message = repository.create_message
get_messages_by_conversation = repository.get_messages_by_conversation
get_recent_user_messages = repository.get_recent_user_messages
