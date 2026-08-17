"""Régressions du repository transactionnel des connexions SSH."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db_connection import db
from repositories.ssh_connections import SSHConnectionRepository
import dpapi_secret_store
import ssh_connection_vault as ssh_vault


def main() -> int:
    with tempfile.TemporaryDirectory() as directory, patch.object(
        dpapi_secret_store,
        "PATH",
        Path(directory) / "ssh-vault.json",
    ):
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
            connection.execute(
                """INSERT INTO ssh_connections
                   (id,name,host,port,username,password,private_key)
                   VALUES ('legacy','Legacy','10.0.0.4',22,'root','legacy-secret','')"""
            )

        repository = SSHConnectionRepository(connection_scope=lambda: db(path))
        assert repository.migrate_legacy_secrets() == 1
        legacy = repository.get_connection("legacy")
        assert legacy["password"] == "legacy-secret"
        with db(path) as connection:
            raw_legacy = connection.execute(
                "SELECT password,private_key,key_passphrase,secret_ref FROM ssh_connections WHERE id='legacy'"
            ).fetchone()
        assert raw_legacy[0:3] == ("", "", "")
        assert raw_legacy[3].startswith("ssh.connection.")
        with patch(
            "repositories.ssh_connections.uuid",
            SimpleNamespace(uuid4=lambda: "ssh-1"),
        ):
            public = repository.save_connection(
                "Debian", "10.0.0.2", 22, "marvin", "secret", "PRIVATE", "phrase"
            )
        assert "password" not in public and "private_key" not in public

        stored = repository.get_connection("ssh-1")
        assert stored["password"] == "secret"
        assert stored["private_key"] == "PRIVATE"
        assert stored["key_passphrase"] == "phrase"
        with db(path) as connection:
            raw = connection.execute(
                "SELECT password,private_key,key_passphrase,secret_ref FROM ssh_connections WHERE id='ssh-1'"
            ).fetchone()
        assert raw[0:3] == ("", "", "") and raw[3]

        resolved = repository.find_connection("10.0.0.2", "marvin", 22)
        assert resolved and resolved["id"] == "ssh-1"
        assert resolved["password"] == "secret"
        assert repository.find_connection("10.0.0.2", "other", 22) is None

        listed = repository.list_connections()
        assert len(listed) == 2
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
            "repositories.ssh_connections.uuid",
            SimpleNamespace(uuid4=lambda: "ssh-1"),
        ):
            try:
                repository.save_connection("Duplicate", "host", 22, "user")
            except ValueError:
                pass
            else:
                raise AssertionError("La contrainte primaire doit provoquer un rollback")
        assert repository.get_connection("ssh-1")["name"] == "Debian"

        with patch.object(
            ssh_vault, "delete", side_effect=RuntimeError("vault unavailable")
        ):
            try:
                repository.delete_connection("ssh-1")
            except RuntimeError:
                pass
            else:
                raise AssertionError("La panne coffre devait restaurer la connexion.")
        assert repository.get_connection("ssh-1") is not None

        repository.delete_connection("ssh-1")
        assert repository.get_connection("ssh-1") is None

        def create(index: int):
            return repository.save_connection(
                f"Node {index}", f"10.0.1.{index + 1}", 22, "marvin",
                private_key=(
                    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                    f"test-{index}\n"
                    "-----END OPENSSH PRIVATE KEY-----"
                ),
                key_passphrase=f"phrase-{index}",
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            created = list(executor.map(create, range(4)))
        assert len({item["id"] for item in created}) == 4
        assert all(
            repository.get_connection(item["id"])["private_key"].startswith(
                "-----BEGIN OPENSSH"
            )
            for item in created
        )
        for item in created:
            repository.delete_connection(item["id"])

        assert repository.rollback_secrets_to_sqlite(confirmed=True) == 1
        with db(path) as connection:
            rolled_back = connection.execute(
                "SELECT password,secret_ref FROM ssh_connections WHERE id='legacy'"
            ).fetchone()
        assert tuple(rolled_back) == ("legacy-secret", "")

    import database
    from repositories import ssh_connections

    assert database.list_ssh_connections is ssh_connections.list_ssh_connections
    assert database.get_ssh_connection is ssh_connections.get_ssh_connection
    assert database.find_ssh_connection is ssh_connections.find_ssh_connection
    assert database.save_ssh_connection is ssh_connections.save_ssh_connection
    print("SSH Repository OK - compatibilité, secrets, CRUD, rollback et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
