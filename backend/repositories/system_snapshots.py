"""Persistance injectable des instantanés de santé système."""

from __future__ import annotations

import math
import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
_MAX_LOOKBACK_DAYS = 3_650


def _finite_number(value: float, field: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} doit être un nombre fini.")
    return number


class SystemSnapshotRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS system_snapshots (
                id TEXT PRIMARY KEY,
                ram_percent REAL,
                disk_max_percent REAL,
                disk_max_percent_drive TEXT,
                disk_max_wear REAL,
                recurring_errors_count INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_system_snapshots_created
               ON system_snapshots(created_at DESC)"""
        )

    def save(
        self,
        ram_percent: float,
        disk_max_percent: float,
        disk_max_percent_drive: str,
        disk_max_wear: float | None,
        recurring_errors_count: int,
    ) -> dict:
        snapshot_id = str(uuid.uuid4())
        normalized_wear = (
            None
            if disk_max_wear is None
            else _finite_number(disk_max_wear, "disk_max_wear")
        )
        normalized_error_count = int(recurring_errors_count)
        if normalized_error_count < 0:
            raise ValueError("recurring_errors_count ne peut pas être négatif.")
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO system_snapshots (
                       id, ram_percent, disk_max_percent,
                       disk_max_percent_drive, disk_max_wear,
                       recurring_errors_count
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    _finite_number(ram_percent, "ram_percent"),
                    _finite_number(disk_max_percent, "disk_max_percent"),
                    str(disk_max_percent_drive),
                    normalized_wear,
                    normalized_error_count,
                ),
            )
        return {"id": snapshot_id}

    def list_recent(self, days: int = 30) -> list[dict]:
        bounded_days = min(max(int(days), 1), _MAX_LOOKBACK_DAYS)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM system_snapshots
                   WHERE created_at >= datetime('now', ?)
                   ORDER BY created_at ASC, id ASC""",
                (f"-{bounded_days} days",),
            ).fetchall()
        return [row_to_dict(row) for row in rows]


repository = SystemSnapshotRepository()
save_system_snapshot = repository.save
get_system_snapshots = repository.list_recent
