"""Régressions SQLite du repository d'événements et calendriers locaux."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.events import EventRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "events.db"
        repository = EventRepository(connection_scope=lambda: db(path))

        with patch("repositories.events.uuid.uuid4", return_value="event-1"):
            created = repository.create(
                "Maintenance",
                "2026-08-20 14:00",
                end_at="2026-08-20 15:00",
                location="Paris",
                reminder_minutes=10,
                tags=["ops"],
            )
        assert created["id"] == "event-1"
        assert created["all_day"] is False and created["tags"] == ["ops"]
        assert repository.list(
            start="2026-08-20 00:00",
            end="2026-08-20 23:59",
        )[0]["id"] == "event-1"

        updated = repository.update(
            "event-1",
            {"all_day": True, "tags": ["validé"], "unknown": "ignored"},
        )
        assert updated["all_day"] is True and updated["tags"] == ["validé"]
        assert repository.update("missing", {"title": "absent"}) is None
        assert repository.needing_reminder("2026-08-20 13:50")[0]["id"] == "event-1"
        assert repository.needing_reminder("date-invalide") == []

        with db(path) as connection:
            connection.execute("UPDATE events SET tags='invalid-json' WHERE id='event-1'")
        assert repository.get("event-1")["tags"] == []

        external = [
            {
                "title": "Calendrier distant",
                "start_at": "2026-08-21T10:00:00",
                "external_id": "remote-1",
            },
            {"title": "Sans date"},
        ]
        with patch("repositories.events.uuid.uuid4", return_value="external-1"):
            assert repository.replace_external("ics:test", external) == 1
        assert repository.count_by_source("ics:test") == 1

        try:
            repository.replace_external(
                "ics:test",
                [{"title": 42, "start_at": "2026-08-22T10:00:00"}],
            )
        except TypeError:
            pass
        else:
            raise AssertionError("Le lot externe invalide doit être annulé.")
        assert repository.count_by_source("ics:test") == 1
        assert repository.delete_by_source("ics:test") == 1
        assert repository.count_by_source("ics:test") == 0

        repository.delete("event-1")
        assert repository.get("event-1") is None

        legacy_path = Path(directory) / "legacy-events.db"
        with db(legacy_path) as connection:
            connection.execute(
                """CREATE TABLE events (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    tags TEXT DEFAULT '[]',
                    all_day INTEGER NOT NULL DEFAULT 0,
                    reminded INTEGER NOT NULL DEFAULT 0
                )"""
            )
        legacy = EventRepository(connection_scope=lambda: db(legacy_path))
        assert legacy.count_by_source("local") == 0
        with db(legacy_path) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(events)").fetchall()
            }
        assert {"source", "external_id"} <= columns

    import database
    from repositories import events

    expected = {
        "create_event": events.create_event,
        "get_event": events.get_event,
        "list_events": events.list_events,
        "update_event": events.update_event,
        "delete_event": events.delete_event,
        "events_needing_reminder": events.events_needing_reminder,
        "replace_external_events": events.replace_external_events,
        "delete_events_by_source": events.delete_events_by_source,
        "count_events_by_source": events.count_events_by_source,
    }
    for name, function in expected.items():
        assert getattr(database, name) is function, name

    print(
        "Event Repository OK - CRUD, rappels, migration, lots externes, "
        "rollback et façades."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
