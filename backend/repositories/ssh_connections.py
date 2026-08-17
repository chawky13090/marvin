"""Repository transactionnel des connexions SSH Marvin."""

from __future__ import annotations

import uuid
import threading
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict
import ssh_connection_vault as vault


ConnectionScope = Callable[[], AbstractContextManager]
PUBLIC_COLUMNS = "id,name,host,port,username,last_used,created_at"
LIST_COLUMNS = PUBLIC_COLUMNS + ",last_test_ok,last_test_at"
_LOCK = threading.RLock()


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
            "secret_ref": "TEXT DEFAULT ''",
            "last_test_ok": "INTEGER",
            "last_test_at": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE ssh_connections ADD COLUMN {name} {declaration}"
                )

    def list_connections(self) -> list[dict[str, Any]]:
        self.migrate_legacy_secrets()
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(
                f"SELECT {LIST_COLUMNS} FROM ssh_connections ORDER BY name"
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        self.migrate_legacy_secrets()
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute(
                "SELECT * FROM ssh_connections WHERE id = ?", (connection_id,)
            ).fetchone()
        result = row_to_dict(row)
        if result and result.get("secret_ref"):
            secrets = vault.load(str(result["secret_ref"]))
            if not secrets:
                raise vault.SSHConnectionVaultError(
                    "Secrets SSH absents du coffre DPAPI."
                )
            result.update(secrets)
        return result

    def find_connection(
        self, host: str, username: str = "", port: int = 22
    ) -> dict[str, Any] | None:
        """Résout une cible chat vers une connexion déjà protégée par le coffre DPAPI."""
        normalized_host = str(host or "").strip().casefold()
        normalized_user = str(username or "").strip().casefold()
        if not normalized_host:
            return None
        matches = [
            item for item in self.list_connections()
            if str(item.get("host") or "").strip().casefold() == normalized_host
            and int(item.get("port") or 22) == int(port or 22)
            and (
                not normalized_user
                or str(item.get("username") or "").strip().casefold() == normalized_user
            )
        ]
        if len(matches) != 1:
            return None
        return self.get_connection(str(matches[0]["id"]))

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
        with _LOCK:
            connection_id = str(uuid.uuid4())
            with self._connection_scope() as connection:
                self.ensure_schema(connection)
                if connection.execute(
                    "SELECT 1 FROM ssh_connections WHERE id=?", (connection_id,)
                ).fetchone():
                    raise ValueError("Collision d'identifiant de connexion SSH.")
            secret_ref = ""
            if password or private_key:
                secret_ref = vault.store(
                    connection_id,
                    {
                        "password": password,
                        "private_key": private_key,
                        "key_passphrase": key_passphrase,
                    },
                )
            try:
                with self._connection_scope() as connection:
                    self.ensure_schema(connection)
                    connection.execute(
                        """INSERT INTO ssh_connections
                           (id,name,host,port,username,password,private_key,key_passphrase,secret_ref)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            connection_id, name, host, port, username,
                            "", "", "", secret_ref,
                        ),
                    )
                    row = connection.execute(
                        f"SELECT {PUBLIC_COLUMNS} FROM ssh_connections WHERE id=?",
                        (connection_id,),
                    ).fetchone()
            except BaseException:
                if secret_ref:
                    vault.delete(secret_ref)
                raise
        result = row_to_dict(row)
        if result is None:
            raise RuntimeError("La connexion SSH créée est introuvable avant commit.")
        return result

    def update_connection(
        self, connection_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        existing = self.get_connection(connection_id)
        if existing is None:
            return None
        allowed = {"name", "host", "port", "username"}
        sets: list[str] = []
        values: list[Any] = []
        for name, value in fields.items():
            if name not in allowed:
                continue
            sets.append(f"{name}=?")
            values.append(value)
        merged_secrets = {
            field: (
                fields.get(field)
                if fields.get(field) not in {None, ""}
                else existing.get(field, "")
            )
            for field in vault.SECRET_FIELDS
        }
        old_secrets = (
            vault.extract(existing)
            if existing.get("password") or existing.get("private_key")
            else {}
        )
        secret_ref = str(existing.get("secret_ref") or "")
        if merged_secrets.get("password") or merged_secrets.get("private_key"):
            secret_ref = vault.store(connection_id, merged_secrets)
        try:
            with self._connection_scope() as connection:
                self.ensure_schema(connection)
                sets.extend([
                    "password=''", "private_key=''", "key_passphrase=''",
                    "secret_ref=?", "updated_at=datetime('now')",
                ])
                values.append(secret_ref)
                connection.execute(
                    f"UPDATE ssh_connections SET {', '.join(sets)} WHERE id=?",
                    (*values, connection_id),
                )
                row = connection.execute(
                    f"SELECT {PUBLIC_COLUMNS} FROM ssh_connections WHERE id=?",
                    (connection_id,),
                ).fetchone()
        except BaseException:
            if old_secrets:
                vault.store(connection_id, old_secrets)
            elif secret_ref:
                vault.delete(secret_ref)
            raise
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
        with _LOCK:
            with self._connection_scope() as connection:
                self.ensure_schema(connection)
                row = connection.execute(
                    "SELECT * FROM ssh_connections WHERE id=?", (connection_id,)
                ).fetchone()
                raw = row_to_dict(row)
                connection.execute(
                    "DELETE FROM ssh_connections WHERE id=?", (connection_id,)
                )
            if not raw or not raw.get("secret_ref"):
                return
            try:
                vault.delete(str(raw["secret_ref"]))
            except BaseException:
                with self._connection_scope() as connection:
                    columns = list(raw)
                    placeholders = ",".join("?" for _ in columns)
                    connection.execute(
                        f"INSERT INTO ssh_connections ({','.join(columns)}) VALUES ({placeholders})",
                        tuple(raw[column] for column in columns),
                    )
                raise

    def migrate_legacy_secrets(self) -> int:
        with _LOCK:
            with self._connection_scope() as connection:
                self.ensure_schema(connection)
                rows = connection.execute(
                    """SELECT * FROM ssh_connections
                       WHERE COALESCE(secret_ref, '') = ''
                         AND (COALESCE(password, '') <> ''
                              OR COALESCE(private_key, '') <> '')"""
                ).fetchall()
            changed = 0
            for row in rows:
                raw = row_to_dict(row)
                if raw is None:
                    continue
                secret_ref = vault.store(str(raw["id"]), raw)
                try:
                    with self._connection_scope() as connection:
                        self.ensure_schema(connection)
                        cursor = connection.execute(
                            """UPDATE ssh_connections
                               SET password='', private_key='', key_passphrase='',
                                   secret_ref=?, updated_at=datetime('now')
                               WHERE id=? AND COALESCE(secret_ref, '')=''""",
                            (secret_ref, raw["id"]),
                        )
                        if cursor.rowcount != 1:
                            raise RuntimeError("Migration SSH concurrente refusée.")
                    changed += 1
                except BaseException:
                    vault.delete(secret_ref)
                    raise
            if changed:
                try:
                    import audit
                    audit.log_action(
                        "ssh_connection_secrets_migrated",
                        result={"success": True, "connections": changed},
                        source="runtime",
                    )
                except Exception:
                    pass
            return changed

    def rollback_secrets_to_sqlite(self, *, confirmed: bool) -> int:
        if confirmed is not True:
            raise ValueError("Confirmation explicite requise.")
        with _LOCK:
            with self._connection_scope() as connection:
                self.ensure_schema(connection)
                rows = connection.execute(
                    "SELECT * FROM ssh_connections WHERE COALESCE(secret_ref, '') <> ''"
                ).fetchall()
            resolved = []
            for row in rows:
                raw = row_to_dict(row)
                if raw is None:
                    continue
                secrets = vault.load(str(raw["secret_ref"]))
                if not secrets:
                    raise vault.SSHConnectionVaultError("Secret SSH absent.")
                resolved.append((raw, secrets))
            with self._connection_scope() as connection:
                for raw, secrets in resolved:
                    connection.execute(
                        """UPDATE ssh_connections
                           SET password=?, private_key=?, key_passphrase=?, secret_ref=''
                           WHERE id=?""",
                        (
                            secrets.get("password", ""),
                            secrets.get("private_key", ""),
                            secrets.get("key_passphrase", ""),
                            raw["id"],
                        ),
                    )
            for raw, _ in resolved:
                vault.delete(str(raw["secret_ref"]))
            return len(resolved)


repository = SSHConnectionRepository()
list_ssh_connections = repository.list_connections
get_ssh_connection = repository.get_connection
find_ssh_connection = repository.find_connection
save_ssh_connection = repository.save_connection
update_ssh_connection = repository.update_connection
set_ssh_test_result = repository.set_test_result
touch_ssh_connection = repository.touch_connection
delete_ssh_connection = repository.delete_connection
migrate_ssh_connection_secrets = repository.migrate_legacy_secrets
rollback_ssh_connection_secrets = repository.rollback_secrets_to_sqlite
