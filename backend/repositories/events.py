"""Persistance injectable de l'agenda local et des miroirs externes."""

from __future__ import annotations

import json
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]


def _parse_event(row: dict | None) -> dict | None:
    if row is None:
        return None
    if row.get("tags") and isinstance(row["tags"], str):
        try:
            row["tags"] = json.loads(row["tags"])
        except json.JSONDecodeError:
            row["tags"] = []
    row["all_day"] = bool(row.get("all_day", 0))
    row["reminded"] = bool(row.get("reminded", 0))
    return row


class EventRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                start_at TEXT NOT NULL,
                end_at TEXT,
                location TEXT DEFAULT '',
                all_day INTEGER NOT NULL DEFAULT 0,
                reminder_minutes INTEGER,
                reminded INTEGER NOT NULL DEFAULT 0,
                color TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                source TEXT DEFAULT 'local',
                external_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_at)"
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(events)").fetchall()
        }
        if "source" not in columns:
            connection.execute(
                "ALTER TABLE events ADD COLUMN source TEXT DEFAULT 'local'"
            )
        if "external_id" not in columns:
            connection.execute("ALTER TABLE events ADD COLUMN external_id TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)"
        )

    def create(
        self,
        title: str,
        start_at: str,
        end_at: str | None = None,
        description: str = "",
        location: str = "",
        all_day: bool = False,
        reminder_minutes: int | None = None,
        color: str = "",
        tags: list | None = None,
    ) -> dict:
        event_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO events (
                       id, title, description, start_at, end_at, location,
                       all_day, reminder_minutes, color, tags
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    title,
                    description,
                    start_at,
                    end_at,
                    location,
                    int(all_day),
                    reminder_minutes,
                    color,
                    json.dumps(tags or []),
                ),
            )
            row = connection.execute(
                "SELECT * FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
        result = _parse_event(row_to_dict(row))
        if result is None:
            raise RuntimeError("L'événement créé est introuvable avant commit.")
        return result

    def get(self, event_id: str) -> dict | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return _parse_event(row_to_dict(row))

    def list(
        self,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[object] = []
        if start:
            sql += " AND start_at >= ?"
            params.append(start)
        if end:
            sql += " AND start_at <= ?"
            params.append(end)
        sql += " ORDER BY start_at ASC LIMIT ?"
        params.append(limit)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(sql, params).fetchall()
        return [_parse_event(row_to_dict(row)) for row in rows]

    def update(self, event_id: str, updates: dict) -> dict | None:
        fields: list[str] = []
        values: list[object] = []
        for key in (
            "title",
            "description",
            "start_at",
            "end_at",
            "location",
            "color",
            "reminder_minutes",
        ):
            if key in updates:
                fields.append(f"{key} = ?")
                values.append(updates[key])
        for key in ("all_day", "reminded"):
            if key in updates:
                fields.append(f"{key} = ?")
                values.append(int(bool(updates[key])))
        if "tags" in updates:
            fields.append("tags = ?")
            values.append(json.dumps(updates["tags"]))
        if not fields:
            return self.get(event_id)
        fields.append("updated_at = datetime('now')")
        values.append(event_id)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                f"UPDATE events SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            row = connection.execute(
                "SELECT * FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return _parse_event(row_to_dict(row))

    def delete(self, event_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def needing_reminder(self, now_iso: str) -> list[dict]:
        try:
            now = datetime.fromisoformat(now_iso)
        except (TypeError, ValueError):
            return []
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM events
                   WHERE reminded = 0
                     AND reminder_minutes IS NOT NULL
                     AND start_at >= ?""",
                (now_iso[:10],),
            ).fetchall()
        due: list[dict] = []
        for row in rows:
            event = _parse_event(row_to_dict(row))
            try:
                start = datetime.fromisoformat(
                    (event["start_at"] or "").replace("T", " ")
                )
                trigger = start - timedelta(
                    minutes=int(event.get("reminder_minutes") or 0)
                )
                if trigger <= now <= start + timedelta(minutes=1):
                    due.append(event)
            except (TypeError, ValueError, OverflowError):
                continue
        return due

    def replace_external(self, source: str, events: list[dict]) -> int:
        inserted = 0
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute("DELETE FROM events WHERE source = ?", (source,))
            for event in events:
                if not event.get("start_at"):
                    continue
                connection.execute(
                    """INSERT INTO events (
                           id, title, description, start_at, end_at, location,
                           all_day, color, tags, source, external_id
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        (event.get("title") or "(sans titre)")[:300],
                        (event.get("description") or "")[:2000],
                        event.get("start_at"),
                        event.get("end_at"),
                        (event.get("location") or "")[:300],
                        int(bool(event.get("all_day"))),
                        event.get("color") or "",
                        source,
                        event.get("external_id"),
                    ),
                )
                inserted += 1
        return inserted

    def delete_by_source(self, source: str) -> int:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            cursor = connection.execute(
                "DELETE FROM events WHERE source = ?",
                (source,),
            )
            return cursor.rowcount or 0

    def count_by_source(self, source: str) -> int:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT COUNT(*) AS c FROM events WHERE source = ?",
                (source,),
            ).fetchone()
        return row["c"] if row else 0


repository = EventRepository()
create_event = repository.create
get_event = repository.get
list_events = repository.list
update_event = repository.update
delete_event = repository.delete
events_needing_reminder = repository.needing_reminder
replace_external_events = repository.replace_external
delete_events_by_source = repository.delete_by_source
count_events_by_source = repository.count_by_source
