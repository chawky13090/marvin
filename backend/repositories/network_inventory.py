"""Persistance injectable de l'inventaire réseau découvert."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
_MAX_LOOKBACK_DAYS = 3_650


class NetworkInventoryRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS network_devices (
                id TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                mac TEXT DEFAULT '',
                hostname TEXT DEFAULT '',
                custom_name TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(mac, ip)
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS idx_network_devices_last_seen
               ON network_devices(last_seen DESC)"""
        )

    def upsert(self, ip: str, mac: str = "", hostname: str = "") -> dict:
        normalized_ip = str(ip).strip()
        if not normalized_ip:
            raise ValueError("L'adresse IP de l'appareil est obligatoire.")
        normalized_mac = str(mac or "").strip()
        normalized_hostname = str(hostname or "").strip()
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            existing = connection.execute(
                """SELECT id FROM network_devices
                   WHERE ip = ? AND mac = ?""",
                (normalized_ip, normalized_mac),
            ).fetchone()
            if existing:
                connection.execute(
                    """UPDATE network_devices
                       SET hostname = ?, last_seen = datetime('now')
                       WHERE id = ?""",
                    (normalized_hostname, existing["id"]),
                )
                return {"id": existing["id"], "new": False}
            device_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO network_devices (id, ip, mac, hostname)
                   VALUES (?, ?, ?, ?)""",
                (
                    device_id,
                    normalized_ip,
                    normalized_mac,
                    normalized_hostname,
                ),
            )
            return {"id": device_id, "new": True}

    def list_recent(self, days: int = 30) -> list[dict]:
        bounded_days = min(max(int(days), 1), _MAX_LOOKBACK_DAYS)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                """SELECT * FROM network_devices
                   WHERE last_seen >= datetime('now', ?)
                   ORDER BY last_seen DESC, id ASC""",
                (f"-{bounded_days} days",),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def set_notes(
        self,
        device_id: str,
        custom_name: str | None = None,
        notes: str | None = None,
    ) -> dict:
        assignments: list[str] = []
        values: list[object] = []
        if custom_name is not None:
            assignments.append("custom_name = ?")
            values.append(str(custom_name))
        if notes is not None:
            assignments.append("notes = ?")
            values.append(str(notes))
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if assignments:
                connection.execute(
                    f"UPDATE network_devices SET {', '.join(assignments)} "
                    "WHERE id = ?",
                    (*values, device_id),
                )
        return {"success": True}


repository = NetworkInventoryRepository()
upsert_network_device = repository.upsert
get_network_devices = repository.list_recent
set_network_device_notes = repository.set_notes
