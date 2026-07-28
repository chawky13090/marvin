"""Régressions SQLite du repository de fiches de révision."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.flashcards import FlashcardRepository


NOW = datetime(2026, 7, 28, 12, 0, 0)


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "flashcards.db"
        repository = FlashcardRepository(
            connection_scope=lambda: db(path),
            clock=lambda: NOW,
        )
        with db(path) as connection:
            repository.ensure_schema(connection)

        with patch(
            "repositories.flashcards.uuid.uuid4",
            return_value="card-a",
        ):
            first = repository.create(
                "Réseau",
                "Port HTTPS ?",
                "443",
                ["80", "443"],
            )
        with patch(
            "repositories.flashcards.uuid.uuid4",
            return_value="card-b",
        ):
            second = repository.create(
                "Réseau",
                "Protocole de résolution de noms ?",
                "DNS",
            )
        assert first["choices"] == ["80", "443"]
        assert second["choices"] == []
        assert repository.next("Réseau")["id"] == "card-a"

        answered = repository.answer("card-a", True)
        assert answered["interval_days"] == 2
        assert answered["correct_count"] == 1
        assert answered["due_at"] == "2026-07-30 12:00:00"
        assert repository.next("Réseau")["id"] == "card-b"
        answered = repository.answer("card-b", False)
        assert answered["interval_days"] == 1
        assert answered["wrong_count"] == 1
        assert answered["due_at"] == "2026-07-29 12:00:00"

        with db(path) as connection:
            connection.execute(
                "UPDATE flashcards SET choices = ?, interval_days = ? "
                "WHERE id = ?",
                ("{invalid", 999, "card-a"),
            )
        assert repository.next("Réseau")["id"] == "card-b"
        repaired = repository.answer("card-a", True)
        assert repaired["interval_days"] == 60
        assert repaired["choices"] == []

        stats = repository.stats()
        assert stats == [
            {
                "topic": "Réseau",
                "total": 2,
                "due_now": 0,
                "correct_total": 2,
                "wrong_total": 1,
            }
        ]
        assert repository.answer("absent", True) is None
        assert repository.next("Absent") is None
        assert repository.next(None) is not None

        invalid_cases = (
            ("", "Question", "Réponse", None),
            ("Sujet", "", "Réponse", None),
            ("Sujet", "Question", "", None),
            ("Sujet", "Question", "Réponse", [""]),
            ("Sujet", "Question", "Réponse", list(map(str, range(21)))),
            ("S" * 201, "Question", "Réponse", None),
            ("Sujet", "Q" * 4_001, "Réponse", None),
            ("Sujet", "Question", "R" * 8_001, None),
            ("Sujet", "Question", "Réponse", ["C" * 2_001]),
        )
        for values in invalid_cases:
            try:
                repository.create(*values)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Fiche invalide acceptée: {values!r}")

        with patch(
            "repositories.flashcards.uuid.uuid4",
            return_value="card-a",
        ):
            try:
                repository.create("Sujet", "Collision", "Réponse")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("La collision doit être annulée.")
        assert repository.delete_by_topic("Réseau") == 2
        assert repository.stats() == []
        try:
            repository.delete_by_topic("")
        except ValueError:
            pass
        else:
            raise AssertionError("Un topic vide doit être refusé.")
        for operation in (
            lambda: repository.next(" "),
            lambda: repository.answer("", True),
            lambda: repository.answer("card-a", "oui"),
        ):
            try:
                operation()
            except ValueError:
                pass
            else:
                raise AssertionError("Une entrée ambiguë doit être refusée.")

    import database
    from repositories import flashcards

    names = (
        "create_flashcard",
        "get_next_flashcard",
        "answer_flashcard",
        "flashcard_stats",
        "delete_flashcards_by_topic",
    )
    for name in names:
        assert getattr(database, name) is getattr(flashcards, name), name

    print(
        "Flashcard Repository OK - sélection déterministe, répétition, "
        "JSON dégradé, bornes, statistiques, rollback et 5 façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
