"""Repository transactionnel des connexions SSH Marvin."""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict


ConnectionScope = Callable[[], AbstractContextManager]
PUBLIC_COLUMNS = "id,name,host,port,username,last_used,created_at"
LIST_COLUMNS = PUBLIC_COLUMNS + ",last_test_ok,last_test_at"


class SSHConnectionRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS ssh_connections (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 22,
                username TEXT NOT NULL,
                password TEXT DEFAULT '',
                private_key TEXT DEFAULT '',
                last_used TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(ssh_connections)")
        }
        additions = {
            "key_passphrase": "TEXT DEFAULT ''",
            "last_test_ok": "INTEGER",
            "last_test_at": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE ssh_connections ADD COLUMN {name} {declaration}"
                )

    def list_connections(self) -> list[dict[str, Any]]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                f"SELECT {LIST_COLUMNS} FROM ssh_connections ORDER BY name"
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM ssh_connections WHERE id = ?", (connection_id,)
            ).fetchone()
        return row_to_dict(row)

    def save_connection(
        self,
        name: str,
        host: str,
        port: int,
        username: str,
        password: str = "",
        private_key: str = "",
        key_passphrase: str = "",
    ) -> dict[str, Any]:
        connection_id = str(uuid.uuid4())
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """INSERT INTO ssh_connections
                   (id,name,host,port,username,password,private_key,key_passphrase)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    connection_id, name, host, port, username,
                    password, private_key, key_passphrase,
                ),
            )
            row = connection.execute(
                f"SELECT {PUBLIC_COLUMNS} FROM ssh_connections WHERE id=?",
                (connection_id,),
            ).fetchone()
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("La connexion SSH créée est introuvable avant commit.")
        return result

    def update_connection(
        self, connection_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        allowed = {
            "name", "host", "port", "username",
            "password", "private_key", "key_passphrase",
        }
        keep_if_empty = {"password", "private_key", "key_passphrase"}
        sets: list[str] = []
        values: list[Any] = []
        for name, value in fields.items():
            if name not in allowed:
                continue
            if name in keep_if_empty and (value is None or value == ""):
                continue
            sets.append(f"{name}=?")
            values.append(value)
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            if sets:
                sets.append("updated_at=datetime('now')")
                connection.execute(
                    f"UPDATE ssh_connections SET {', '.join(sets)} WHERE id=?",
                    (*values, connection_id),
                )
            row = connection.execute(
                f"SELECT {PUBLIC_COLUMNS} FROM ssh_connections WHERE id=?",
                (connection_id,),
            ).fetchone()
        return row_to_dict(row)

    def set_test_result(self, connection_id: str, ok: bool) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                """UPDATE ssh_connections
                   SET last_test_ok=?, last_test_at=datetime('now') WHERE id=?""",
                (1 if ok else 0, connection_id),
            )

    def touch_connection(self, connection_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "UPDATE ssh_connections SET last_used=datetime('now') WHERE id=?",
                (connection_id,),
            )

    def delete_connection(self, connection_id: str) -> None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            connection.execute(
                "DELETE FROM ssh_connections WHERE id=?", (connection_id,)
            )


repository = SSHConnectionRepository()
list_ssh_connections = repository.list_connections
get_ssh_connection = repository.get_connection
save_ssh_connection = repository.save_connection
update_ssh_connection = repository.update_connection
set_ssh_test_result = repository.set_test_result
touch_ssh_connection = repository.touch_connection
delete_ssh_connection = repository.delete_connection
