"""Persistance autoritative des faits et réponses appris par Marvin."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import AbstractContextManager
from typing import Callable, Literal

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
KnowledgeKind = Literal["fact", "qa"]
MAX_TEXT = 4_000
MAX_ANSWER = 12_000
MAX_SOURCE = 120
MAX_ID = 160


def _required(value: object, *, field: str, limit: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} est requis.")
    if len(normalized) > limit:
        raise ValueError(f"{field} dépasse la limite de {limit} caractères.")
    return normalized


def _fingerprint(kind: KnowledgeKind, question: str, answer: str) -> str:
    material = f"{kind}\0{question}\0{answer}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


class LearnedKnowledgeRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS learned_knowledge (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('fact', 'qa')),
                question TEXT NOT NULL,
                answer TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(kind, fingerprint)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_learned_knowledge_kind "
            "ON learned_knowledge(kind, created_at DESC)"
        )

    def upsert(
        self,
        kind: KnowledgeKind,
        question: str,
        answer: str = "",
        *,
        source: str,
        knowledge_id: str | None = None,
    ) -> tuple[dict, bool]:
        if kind not in {"fact", "qa"}:
            raise ValueError("Type de connaissance invalide.")
        normalized_question = _required(
            question,
            field="question",
            limit=MAX_TEXT,
        )
        normalized_answer = (
            _required(answer, field="answer", limit=MAX_ANSWER)
            if kind == "qa"
            else ""
        )
        normalized_source = _required(
            source,
            field="source",
            limit=MAX_SOURCE,
        )
        normalized_id = str(knowledge_id or uuid.uuid4()).strip()
        if not normalized_id or len(normalized_id) > MAX_ID:
            raise ValueError("Identifiant de connaissance invalide.")
        fingerprint = _fingerprint(kind, normalized_question, normalized_answer)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            existing = connection.execute(
                """SELECT * FROM learned_knowledge
                   WHERE kind = ? AND fingerprint = ?""",
                (kind, fingerprint),
            ).fetchone()
            if existing is not None:
                return dict(existing), False
            connection.execute(
                """INSERT INTO learned_knowledge (
                       id, kind, question, answer, source, fingerprint
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    normalized_id,
                    kind,
                    normalized_question,
                    normalized_answer,
                    normalized_source,
                    fingerprint,
                ),
            )
            row = connection.execute(
                "SELECT * FROM learned_knowledge WHERE id = ?",
                (normalized_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("La connaissance créée est introuvable.")
        return result, True

    def list(self, kind: KnowledgeKind, limit: int = 100) -> list[dict]:
        if kind not in {"fact", "qa"}:
            raise ValueError("Type de connaissance invalide.")
        bounded_limit = max(1, min(int(limit), 1_000))
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM learned_knowledge
                   WHERE kind = ?
                   ORDER BY created_at DESC, id ASC
                   LIMIT ?""",
                (kind, bounded_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, kind: KnowledgeKind, knowledge_id: str) -> bool:
        if kind not in {"fact", "qa"}:
            raise ValueError("Type de connaissance invalide.")
        normalized_id = _required(
            knowledge_id,
            field="knowledge_id",
            limit=MAX_ID,
        )
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            cursor = connection.execute(
                "DELETE FROM learned_knowledge WHERE kind = ? AND id = ?",
                (kind, normalized_id),
            )
        return cursor.rowcount == 1

    def counts(self) -> dict[str, int]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT kind, COUNT(*) AS count
                   FROM learned_knowledge GROUP BY kind"""
            ).fetchall()
        values = {str(row["kind"]): int(row["count"]) for row in rows}
        return {"facts": values.get("fact", 0), "qa": values.get("qa", 0)}


repository = LearnedKnowledgeRepository()
