"""Repository injectable des slots de conversation et directives de pilotage."""

from __future__ import annotations

import json
import re
import uuid
from contextlib import AbstractContextManager
from typing import Callable


ConnectionScope = Callable[[], AbstractContextManager]
KINDS = frozenset({"append", "redirect", "next", "stop"})
STATES = frozenset({"received", "deferred", "applied", "rejected", "cancelled"})
TERMINAL_STATES = frozenset({"applied", "rejected", "cancelled"})
TRANSITIONS = {
    "received": frozenset({"deferred", "applied", "rejected", "cancelled"}),
    "deferred": frozenset({"applied", "rejected", "cancelled"}),
    "applied": frozenset(),
    "rejected": frozenset(),
    "cancelled": frozenset(),
}
MAX_DIRECTIVES_PER_TURN = 32
MAX_TEXT_CHARACTERS = 8000
MAX_NEXT_PENDING = 8
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


class DirectiveRepositoryError(RuntimeError):
    pass


class ConversationBusyError(DirectiveRepositoryError):
    pass


class DirectiveConflictError(DirectiveRepositoryError):
    pass


class DirectiveLimitError(DirectiveRepositoryError):
    pass


class InvalidDirectiveTransition(DirectiveRepositoryError):
    pass


def _identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"{label} invalide.")
    return normalized


def _uuid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{label} doit être un UUID.") from exc


def _row(row) -> dict | None:
    return dict(row) if row is not None else None


class ChatTurnDirectiveRepository:
    def __init__(self, connection_scope: ConnectionScope) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS chat_turn_slots (
                conversation_key TEXT PRIMARY KEY,
                root_request_id TEXT NOT NULL UNIQUE,
                conversation_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS chat_turn_directives (
                id TEXT PRIMARY KEY,
                client_directive_id TEXT NOT NULL,
                root_request_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('append','redirect','next','stop')),
                directive_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'received'
                    CHECK(status IN ('received','deferred','applied','rejected','cancelled')),
                waiting_for_json TEXT,
                reason_code TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                applied_at TEXT,
                UNIQUE(root_request_id, client_directive_id),
                UNIQUE(root_request_id, sequence)
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_chat_turn_directives_status
               ON chat_turn_directives(root_request_id, status, sequence)"""
        )

    def reserve_slot(
        self,
        *,
        conversation_key: str,
        root_request_id: str,
        conversation_id: str = "",
    ) -> dict:
        key = _identifier(conversation_key, "conversation_key")
        request = _identifier(root_request_id, "root_request_id")
        final_id = _identifier(conversation_id, "conversation_id") if conversation_id else ""
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.ensure_schema(connection)
            existing = connection.execute(
                "SELECT * FROM chat_turn_slots WHERE conversation_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                if str(existing["root_request_id"]) != request:
                    raise ConversationBusyError("Cette conversation possède déjà un tour actif.")
                return dict(existing)
            other = connection.execute(
                "SELECT conversation_key FROM chat_turn_slots WHERE root_request_id = ?",
                (request,),
            ).fetchone()
            if other is not None:
                raise DirectiveConflictError("Ce tour racine est déjà lié à une autre conversation.")
            connection.execute(
                """INSERT INTO chat_turn_slots
                   (conversation_key, root_request_id, conversation_id)
                   VALUES (?, ?, ?)""",
                (key, request, final_id),
            )
            return dict(connection.execute(
                "SELECT * FROM chat_turn_slots WHERE conversation_key = ?", (key,)
            ).fetchone())

    def release_slot(self, *, conversation_key: str, root_request_id: str) -> bool:
        key = _identifier(conversation_key, "conversation_key")
        request = _identifier(root_request_id, "root_request_id")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            deleted = connection.execute(
                "DELETE FROM chat_turn_slots WHERE conversation_key = ? AND root_request_id = ?",
                (key, request),
            ).rowcount
            return deleted == 1

    def rebind_slot(
        self,
        *,
        provisional_key: str,
        conversation_key: str,
        conversation_id: str,
        root_request_id: str,
    ) -> dict:
        old_key = _uuid(provisional_key, "provisional_key")
        new_key = _identifier(conversation_key, "conversation_key")
        final_id = _identifier(conversation_id, "conversation_id")
        request = _identifier(root_request_id, "root_request_id")
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.ensure_schema(connection)
            source = connection.execute(
                "SELECT * FROM chat_turn_slots WHERE conversation_key = ? AND root_request_id = ?",
                (old_key, request),
            ).fetchone()
            if source is None:
                raise DirectiveConflictError("Le slot provisoire attendu est absent.")
            collision = connection.execute(
                "SELECT root_request_id FROM chat_turn_slots WHERE conversation_key = ?",
                (new_key,),
            ).fetchone()
            if collision is not None and str(collision["root_request_id"]) != request:
                raise ConversationBusyError("La conversation finale possède déjà un autre tour actif.")
            connection.execute(
                """UPDATE chat_turn_slots
                   SET conversation_key = ?, conversation_id = ?, updated_at = datetime('now')
                   WHERE conversation_key = ? AND root_request_id = ?""",
                (new_key, final_id, old_key, request),
            )
            return dict(connection.execute(
                "SELECT * FROM chat_turn_slots WHERE conversation_key = ?", (new_key,)
            ).fetchone())

    def create_directive(
        self,
        *,
        root_request_id: str,
        client_directive_id: str,
        kind: str,
        text: str = "",
    ) -> tuple[dict, bool]:
        request = _identifier(root_request_id, "root_request_id")
        client_id = _uuid(client_directive_id, "client_directive_id")
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in KINDS:
            raise ValueError("Type de directive invalide.")
        normalized_text = str(text or "").strip()
        if normalized_kind != "stop" and not normalized_text:
            raise ValueError("Le texte de la directive est obligatoire.")
        if normalized_kind == "stop" and normalized_text:
            raise ValueError("Une directive stop ne porte pas de texte libre.")
        if len(normalized_text) > MAX_TEXT_CHARACTERS:
            raise DirectiveLimitError("La directive dépasse la taille autorisée.")

        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.ensure_schema(connection)
            slot = connection.execute(
                "SELECT 1 FROM chat_turn_slots WHERE root_request_id = ?", (request,)
            ).fetchone()
            if slot is None:
                raise DirectiveConflictError("Le tour racine actif est absent.")
            existing = connection.execute(
                """SELECT * FROM chat_turn_directives
                   WHERE root_request_id = ? AND client_directive_id = ?""",
                (request, client_id),
            ).fetchone()
            if existing is not None:
                value = dict(existing)
                if value["kind"] != normalized_kind or value["directive_text"] != normalized_text:
                    raise DirectiveConflictError("Cet identifiant de directive porte un autre contenu.")
                return value, False
            count = int(connection.execute(
                "SELECT COUNT(*) FROM chat_turn_directives WHERE root_request_id = ?",
                (request,),
            ).fetchone()[0])
            if count >= MAX_DIRECTIVES_PER_TURN:
                raise DirectiveLimitError("Le nombre maximal de directives du tour est atteint.")
            if normalized_kind == "next":
                pending_next = int(connection.execute(
                    """SELECT COUNT(*) FROM chat_turn_directives
                       WHERE root_request_id = ? AND kind = 'next'
                         AND status IN ('received','deferred')""",
                    (request,),
                ).fetchone()[0])
                if pending_next >= MAX_NEXT_PENDING:
                    raise DirectiveLimitError("La file des tâches suivantes est pleine.")
            if normalized_kind in {"append", "redirect"}:
                stopped = connection.execute(
                    """SELECT 1 FROM chat_turn_directives
                       WHERE root_request_id = ? AND kind = 'stop'
                         AND status IN ('received','deferred','applied') LIMIT 1""",
                    (request,),
                ).fetchone()
                if stopped is not None:
                    raise DirectiveConflictError("Un arrêt est déjà demandé pour ce tour.")
            if normalized_kind == "redirect":
                connection.execute(
                    """UPDATE chat_turn_directives
                       SET status = 'cancelled', reason_code = 'superseded_by_redirect',
                           updated_at = datetime('now')
                       WHERE root_request_id = ? AND kind = 'redirect'
                         AND status IN ('received','deferred')""",
                    (request,),
                )
            sequence = int(connection.execute(
                """SELECT COALESCE(MAX(sequence), 0) + 1
                   FROM chat_turn_directives WHERE root_request_id = ?""",
                (request,),
            ).fetchone()[0])
            directive_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO chat_turn_directives
                   (id, client_directive_id, root_request_id, sequence, kind, directive_text)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (directive_id, client_id, request, sequence, normalized_kind, normalized_text),
            )
            return dict(connection.execute(
                "SELECT * FROM chat_turn_directives WHERE id = ?", (directive_id,)
            ).fetchone()), True

    def transition(
        self,
        directive_id: str,
        *,
        expected_status: str,
        target_status: str,
        waiting_for: dict | None = None,
        reason_code: str = "",
    ) -> dict:
        identifier = _uuid(directive_id, "directive_id")
        source = str(expected_status or "").strip().lower()
        target = str(target_status or "").strip().lower()
        if source not in STATES or target not in TRANSITIONS[source]:
            raise InvalidDirectiveTransition(f"Transition interdite : {source} -> {target}.")
        waiting_json = None
        if target == "deferred":
            if not isinstance(waiting_for, dict) or not waiting_for.get("kind"):
                raise ValueError("Une directive différée exige une cause structurée.")
            waiting_json = json.dumps(waiting_for, ensure_ascii=False, sort_keys=True)
        elif waiting_for is not None:
            raise ValueError("waiting_for est réservé à l'état deferred.")
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.ensure_schema(connection)
            updated = connection.execute(
                """UPDATE chat_turn_directives
                   SET status = ?, waiting_for_json = ?, reason_code = ?,
                       updated_at = datetime('now'),
                       applied_at = CASE WHEN ? = 'applied' THEN datetime('now') ELSE applied_at END
                   WHERE id = ? AND status = ?""",
                (target, waiting_json, str(reason_code)[:120], target, identifier, source),
            ).rowcount
            if updated != 1:
                row = connection.execute(
                    "SELECT status FROM chat_turn_directives WHERE id = ?", (identifier,)
                ).fetchone()
                if row is None:
                    raise DirectiveConflictError("Directive introuvable.")
                raise InvalidDirectiveTransition(
                    f"La directive est déjà dans l'état {row['status']}."
                )
            return dict(connection.execute(
                "SELECT * FROM chat_turn_directives WHERE id = ?", (identifier,)
            ).fetchone())

    def cancel(self, directive_id: str) -> dict:
        identifier = _uuid(directive_id, "directive_id")
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.ensure_schema(connection)
            updated = connection.execute(
                """UPDATE chat_turn_directives
                   SET status = 'cancelled', reason_code = 'owner_cancelled',
                       updated_at = datetime('now')
                   WHERE id = ? AND status IN ('received','deferred')""",
                (identifier,),
            ).rowcount
            row = connection.execute(
                "SELECT * FROM chat_turn_directives WHERE id = ?", (identifier,)
            ).fetchone()
            if row is None:
                raise DirectiveConflictError("Directive introuvable.")
            if updated != 1:
                raise InvalidDirectiveTransition(
                    f"Une directive {row['status']} ne peut plus être annulée."
                )
            return dict(row)

    def list_for_turn(self, root_request_id: str, *, limit: int = 100) -> list[dict]:
        request = _identifier(root_request_id, "root_request_id")
        bounded = max(1, min(int(limit), 100))
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM chat_turn_directives
                   WHERE root_request_id = ? ORDER BY sequence ASC LIMIT ?""",
                (request, bounded),
            ).fetchall()
        return [dict(row) for row in rows]

    def slot_for_root(self, root_request_id: str) -> dict | None:
        request = _identifier(root_request_id, "root_request_id")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM chat_turn_slots WHERE root_request_id = ?", (request,)
            ).fetchone()
        return dict(row) if row is not None else None

    def slot_for_conversation(self, conversation_key: str) -> dict | None:
        key = _identifier(conversation_key, "conversation_key")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM chat_turn_slots WHERE conversation_key = ?", (key,)
            ).fetchone()
        return dict(row) if row is not None else None

    def release_root(self, root_request_id: str) -> bool:
        request = _identifier(root_request_id, "root_request_id")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            return connection.execute(
                "DELETE FROM chat_turn_slots WHERE root_request_id = ?", (request,)
            ).rowcount == 1
