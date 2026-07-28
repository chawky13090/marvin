"""Persistance injectable et déterministe des fiches de révision."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
Clock = Callable[[], datetime]
MAX_TOPIC_LENGTH = 200
MAX_QUESTION_LENGTH = 4_000
MAX_ANSWER_LENGTH = 8_000
MAX_CHOICE_LENGTH = 2_000
MAX_CHOICES = 20
MAX_ID_LENGTH = 160


def _text(value: Any, *, field: str, limit: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} est requis.")
    if len(normalized) > limit:
        raise ValueError(f"{field} dépasse la limite de {limit} caractères.")
    return normalized


def _project(row: dict | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    choices = result.get("choices")
    if isinstance(choices, str):
        try:
            choices = json.loads(choices)
        except json.JSONDecodeError:
            choices = []
    result["choices"] = choices if isinstance(choices, list) else []
    return result


class FlashcardRepository:
    def __init__(
        self,
        connection_scope: ConnectionScope = db,
        clock: Clock = datetime.now,
    ) -> None:
        self._connection_scope = connection_scope
        self._clock = clock

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS flashcards (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                choices TEXT DEFAULT '[]',
                interval_days INTEGER NOT NULL DEFAULT 1,
                due_at TEXT NOT NULL DEFAULT (datetime('now')),
                correct_count INTEGER NOT NULL DEFAULT 0,
                wrong_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_flashcards_due "
            "ON flashcards(due_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_flashcards_topic "
            "ON flashcards(topic)"
        )

    def create(
        self,
        topic: str,
        question: str,
        answer: str,
        choices: list | None = None,
    ) -> dict:
        raw_choices = choices if isinstance(choices, list) else []
        if len(raw_choices) > MAX_CHOICES or any(
            not isinstance(choice, str)
            or not choice.strip()
            or len(choice.strip()) > MAX_CHOICE_LENGTH
            for choice in raw_choices
        ):
            raise ValueError(
                f"choices doit contenir au plus {MAX_CHOICES} chaînes non vides "
                f"de {MAX_CHOICE_LENGTH} caractères maximum."
            )
        normalized_choices = [choice.strip() for choice in raw_choices]
        flashcard_id = str(uuid.uuid4())
        now = self._clock().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO flashcards (
                       id, topic, question, answer, choices, due_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    flashcard_id,
                    _text(topic, field="topic", limit=MAX_TOPIC_LENGTH),
                    _text(
                        question,
                        field="question",
                        limit=MAX_QUESTION_LENGTH,
                    ),
                    _text(answer, field="answer", limit=MAX_ANSWER_LENGTH),
                    json.dumps(normalized_choices, ensure_ascii=False),
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM flashcards WHERE id = ?",
                (flashcard_id,),
            ).fetchone()
        result = _project(row_to_dict(row))
        if result is None:
            raise RuntimeError(
                "La fiche créée est introuvable après insertion."
            )
        return result

    def next(self, topic: str | None = None) -> dict | None:
        now = self._clock().strftime("%Y-%m-%d %H:%M:%S")
        params: list[Any] = [now]
        sql = "SELECT * FROM flashcards WHERE due_at <= ?"
        normalized_topic = (
            _text(topic, field="topic", limit=MAX_TOPIC_LENGTH)
            if topic is not None
            else None
        )
        if normalized_topic:
            sql += " AND topic = ?"
            params.append(normalized_topic)
        sql += " ORDER BY due_at ASC, created_at ASC, id ASC LIMIT 1"
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(sql, params).fetchone()
            if row is None:
                fallback = "SELECT * FROM flashcards"
                fallback_params: tuple[Any, ...] = ()
                if normalized_topic:
                    fallback += " WHERE topic = ?"
                    fallback_params = (normalized_topic,)
                fallback += (
                    " ORDER BY (correct_count + wrong_count) ASC, "
                    "due_at ASC, created_at ASC, id ASC LIMIT 1"
                )
                row = connection.execute(
                    fallback,
                    fallback_params,
                ).fetchone()
        return _project(row_to_dict(row))

    def answer(self, flashcard_id: str, correct: bool) -> dict | None:
        normalized_id = _text(
            flashcard_id,
            field="flashcard_id",
            limit=MAX_ID_LENGTH,
        )
        if not isinstance(correct, bool):
            raise ValueError("correct doit être un booléen.")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM flashcards WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                return None
            current_interval = min(
                max(int(row["interval_days"] or 1), 1),
                60,
            )
            interval = min(current_interval * 2, 60) if correct else 1
            due_at = (
                self._clock() + timedelta(days=interval)
            ).strftime("%Y-%m-%d %H:%M:%S")
            counter = "correct_count" if correct else "wrong_count"
            connection.execute(
                f"""UPDATE flashcards
                    SET interval_days = ?, due_at = ?,
                        {counter} = {counter} + 1
                    WHERE id = ?""",
                (interval, due_at, normalized_id),
            )
            updated = connection.execute(
                "SELECT * FROM flashcards WHERE id = ?",
                (normalized_id,),
            ).fetchone()
        return _project(row_to_dict(updated))

    def stats(self) -> list[dict]:
        now = self._clock().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT topic, COUNT(*) AS total,
                          SUM(CASE WHEN due_at <= ? THEN 1 ELSE 0 END)
                              AS due_now,
                          SUM(correct_count) AS correct_total,
                          SUM(wrong_count) AS wrong_total
                   FROM flashcards
                   GROUP BY topic
                   ORDER BY topic""",
                (now,),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def delete_by_topic(self, topic: str) -> int:
        normalized_topic = _text(
            topic,
            field="topic",
            limit=MAX_TOPIC_LENGTH,
        )
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            cursor = connection.execute(
                "DELETE FROM flashcards WHERE topic = ?",
                (normalized_topic,),
            )
            return cursor.rowcount


repository = FlashcardRepository()
create_flashcard = repository.create
get_next_flashcard = repository.next
answer_flashcard = repository.answer
flashcard_stats = repository.stats
delete_flashcards_by_topic = repository.delete_by_topic
