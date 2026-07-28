"""Régressions du repository transactionnel des paramètres Marvin."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.settings import SettingsRepository


def _create_schema(path: Path) -> None:
    with db(path) as connection:
        connection.execute(
            """CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "settings.db"
        _create_schema(path)
        repository = SettingsRepository(connection_scope=lambda: db(path))

        sentinel = object()
        assert repository.get("missing", sentinel) is sentinel

        cases = {
            "plain": "balanced",
            "mapping": {"enabled": True, "limit": 5},
            "list": ["one", 2, False],
            "integer": 42,
            "boolean": False,
            "nullable": None,
        }
        for key, value in cases.items():
            repository.set(key, value)
            assert repository.get(key, sentinel) == value

        repository.set("legacy-json-string", '{"mode":"manual"}')
        assert repository.get("legacy-json-string") == {"mode": "manual"}

        injection_key = "x' OR 1=1 --"
        repository.set(injection_key, "safe")
        assert repository.get(injection_key) == "safe"
        assert repository.get("plain") == "balanced"

        with db(path) as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("legacy-invalid-json", "{invalid"),
            )
        assert repository.get("legacy-invalid-json") == "{invalid"

        before = repository.get("mapping")
        try:
            repository.set("mapping", {"unsupported": {1, 2}})
        except TypeError:
            pass
        else:
            raise AssertionError("Une valeur non sérialisable doit être refusée.")
        assert repository.get("mapping") == before

        with closing(sqlite3.connect(path)) as connection:
            raw = connection.execute(
                "SELECT value FROM settings WHERE key = ?",
                ("mapping",),
            ).fetchone()[0]
        assert json.loads(raw) == before

    import database
    from repositories import settings

    assert database.get_setting is settings.get_setting
    assert database.set_setting is settings.set_setting
    print(
        "Settings Repository OK - types, compatibilité JSON, paramètres SQL, "
        "atomicité et façade."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
