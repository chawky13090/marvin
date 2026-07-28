"""Persistance injectable des paramètres globaux de Marvin."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db


ConnectionScope = Callable[[], AbstractContextManager]


class SettingsRepository:
    """Stocke les valeurs JSON tout en préservant le format texte historique."""

    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    def get(self, key: str, default: Any = None) -> Any:
        with self._connection_scope() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return default
        value = row["value"]
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value

    def set(self, key: str, value: Any) -> None:
        serialized = value if isinstance(value, str) else json.dumps(value)
        with self._connection_scope() as connection:
            connection.execute(
                """INSERT INTO settings (key, value, updated_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(key) DO UPDATE SET
                     value = excluded.value,
                     updated_at = excluded.updated_at""",
                (key, serialized),
            )


repository = SettingsRepository()
get_setting = repository.get
set_setting = repository.set
