"""Contrat de maintenance SQLite hors ligne et compensable."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import sqlite_maintenance
from sqlite_maintenance import SqliteMaintenance


MARKER = "MARVIN-SENSITIVE-DELETED-MARKER-" + "X" * 4096


def _create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA secure_delete=OFF")
        connection.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO records(value) VALUES (?)", ("kept",))
        connection.execute("INSERT INTO records(value) VALUES (?)", (MARKER,))
        connection.commit()
        connection.execute("DELETE FROM records WHERE value = ?", (MARKER,))
        connection.commit()
        connection.execute("PRAGMA journal_mode=WAL")
    finally:
        connection.close()
    with path.open("ab") as stream:
        stream.write(MARKER.encode("utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-sqlite-maintenance-") as directory:
        root = Path(directory)
        database = root / "secretary.db"
        _create_database(database)
        assert MARKER.encode("utf-8") in database.read_bytes()

        active = SqliteMaintenance(
            database,
            root / "backups-active",
            root / "reports-active",
            runtime_probe=lambda: True,
        )
        refused = active.run()
        assert refused["success"] is False
        assert refused["phase"] == "preflight"
        assert refused["backup_filename"] is None

        maintenance = SqliteMaintenance(
            database,
            root / "backups",
            root / "reports",
            runtime_probe=lambda: False,
        )
        result = maintenance.run()
        assert result["success"] is True, result
        assert result["integrity"] == "ok"
        assert result["foreign_keys"] == "ok"
        assert result["checkpoint_after"]["busy"] == 0
        assert MARKER.encode("utf-8") not in database.read_bytes()
        assert Path(result["report_path"]).is_file()

        connection = sqlite3.connect(database)
        try:
            connection.execute("UPDATE records SET value='changed'")
            connection.commit()
        finally:
            connection.close()
        rollback = maintenance.rollback(result["backup_filename"])
        assert rollback["success"] is True
        assert rollback["offline_verified"] is True
        connection = sqlite3.connect(database)
        try:
            values = [row[0] for row in connection.execute("SELECT value FROM records")]
        finally:
            connection.close()
        assert values == ["kept"]

        failure_database = root / "failure.db"
        _create_database(failure_database)
        failure_maintenance = SqliteMaintenance(
            failure_database,
            root / "backups-failure",
            root / "reports-failure",
            runtime_probe=lambda: False,
        )
        original_validate = sqlite_maintenance._validate
        validation_calls = 0

        def fail_after_vacuum(connection):
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 2:
                raise sqlite_maintenance.SqliteMaintenanceError("post-check failed")
            return original_validate(connection)

        with patch.object(sqlite_maintenance, "_validate", side_effect=fail_after_vacuum):
            compensated = failure_maintenance.run()
        assert compensated["success"] is False
        assert compensated["phase"] == "integrity_after"
        assert compensated["compensated"] is True
        connection = sqlite3.connect(failure_database)
        try:
            assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        finally:
            connection.close()

    print("SQLite Maintenance OK - offline, backup, VACUUM, intégrité et rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
