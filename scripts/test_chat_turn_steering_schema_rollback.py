from __future__ import annotations

import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from db_migrations import MIGRATIONS, apply_migrations, current_schema_version
from rollback_chat_turn_steering_schema import rollback


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "secretary.db"
        with closing(sqlite3.connect(database)) as connection:
            apply_migrations(
                connection,
                tuple(migration for migration in MIGRATIONS if migration.version <= 7),
            )
            connection.execute(
                "INSERT INTO chat_turn_slots(conversation_key,root_request_id) VALUES('conversation:test','request:test')"
            )
            connection.commit()
            assert current_schema_version(connection) == 7
        result = rollback(database, confirmed=True)
        assert result["schema_version"] == 6
        assert Path(result["backup"]).is_file()
        with closing(sqlite3.connect(database)) as connection:
            assert current_schema_version(connection) == 6
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert "chat_turn_slots" not in tables
            assert "chat_turn_directives" not in tables
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        try:
            rollback(database, confirmed=False)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Le rollback sans confirmation devait etre refuse.")
    print("Chat Turn Steering Schema Rollback OK - backup, down migration and integrity")


if __name__ == "__main__":
    main()
