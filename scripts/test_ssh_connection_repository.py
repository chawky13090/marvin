"""Régressions du repository transactionnel des connexions SSH."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.ssh_connections import SSHConnectionRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ssh.db"
        with db(path) as connection:
            connection.execute(
                """CREATE TABLE ssh_connections (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, host TEXT NOT NULL,
                    port INTEGER NOT NULL DEFAULT 22, username TEXT NOT NULL,
                    password TEXT DEFAULT '', private_key TEXT DEFAULT '',
                    last_used TEXT, created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )"""
            )

        repository = SSHConnectionRepository(connection_scope=lambda: db(path))
        with patch(
            "repositories.ssh_connections.uuid.uuid4", return_value="ssh-1"
        ):
            public = repository.save_connection(
                "Debian", "10.0.0.2", 22, "marvin", "secret", "PRIVATE", "phrase"
            )
        assert "password" not in public and "private_key" not in public

        stored = repository.get_connection("ssh-1")
        assert stored["password"] == "secret"
        assert stored["private_key"] == "PRIVATE"
        assert stored["key_passphrase"] == "phrase"

        listed = repository.list_connections()
        assert len(listed) == 1
        assert "password" not in listed[0] and "private_key" not in listed[0]

        updated = repository.update_connection(
            "ssh-1", host="10.0.0.3", password="", private_key="", forbidden="x"
        )
        assert updated["host"] == "10.0.0.3"
        stored = repository.get_connection("ssh-1")
        assert stored["password"] == "secret" and "forbidden" not in stored

        repository.set_test_result("ssh-1", True)
        repository.touch_connection("ssh-1")
        state = repository.list_connections()[0]
        assert state["last_test_ok"] == 1
        assert state["last_test_at"] and state["last_used"]

        with patch(
            "repositories.ssh_connections.uuid.uuid4", return_value="ssh-1"
        ):
            try:
                repository.save_connection("Duplicate", "host", 22, "user")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("La contrainte primaire doit provoquer un rollback")
        assert repository.get_connection("ssh-1")["name"] == "Debian"

        repository.delete_connection("ssh-1")
        assert repository.get_connection("ssh-1") is None

    import database
    from repositories import ssh_connections

    assert database.list_ssh_connections is ssh_connections.list_ssh_connections
    assert database.get_ssh_connection is ssh_connections.get_ssh_connection
    assert database.save_ssh_connection is ssh_connections.save_ssh_connection
    print("SSH Repository OK - compatibilité, secrets, CRUD, rollback et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
