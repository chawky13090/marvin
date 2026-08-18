"""Profils SNMPv3 publics en SQLite et secrets séparés sous DPAPI."""
from __future__ import annotations

import threading
import uuid
from contextlib import AbstractContextManager
from typing import Any, Callable

from db_connection import db, row_to_dict
import snmp_profile_vault as vault

ConnectionScope = Callable[[], AbstractContextManager]
_AUTH = {"sha1", "sha256"}
_PRIV = {"none", "aes128"}
_LOCK = threading.RLock()
_PUBLIC = "id,name,username,auth_protocol,priv_protocol,context_name,port,last_test_ok,last_test_at,created_at,updated_at"


class SNMPProfileRepository:
    def __init__(self, connection_scope: ConnectionScope = db) -> None:
        self._connection_scope = connection_scope

    @staticmethod
    def ensure_schema(connection) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS snmp_profiles (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, username TEXT NOT NULL,
            auth_protocol TEXT NOT NULL CHECK(auth_protocol IN ('sha1','sha256')),
            priv_protocol TEXT NOT NULL CHECK(priv_protocol IN ('none','aes128')),
            context_name TEXT NOT NULL DEFAULT '', port INTEGER NOT NULL DEFAULT 161 CHECK(port BETWEEN 1 AND 65535),
            secret_ref TEXT NOT NULL, last_test_ok INTEGER, last_test_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")

    @staticmethod
    def _public(row) -> dict[str, Any] | None:
        result = row_to_dict(row)
        if result is not None and result.get("last_test_ok") is not None:
            result["last_test_ok"] = bool(result["last_test_ok"])
        return result

    @staticmethod
    def _validate(name: str, username: str, auth_protocol: str, priv_protocol: str, context_name: str, port: int):
        values = (str(name or "").strip(), str(username or "").strip(), str(auth_protocol or "sha256").strip().lower(), str(priv_protocol or "aes128").strip().lower(), str(context_name or "").strip(), int(port))
        if not values[0] or len(values[0]) > 160 or not values[1] or len(values[1]) > 64:
            raise ValueError("Nom ou utilisateur SNMPv3 invalide.")
        if values[2] not in _AUTH or values[3] not in _PRIV:
            raise ValueError("Protocoles SNMPv3 non pris en charge.")
        if len(values[4]) > 64 or not 1 <= values[5] <= 65535:
            raise ValueError("Contexte ou port SNMPv3 invalide.")
        return values

    def list(self) -> list[dict[str, Any]]:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            rows = connection.execute(f"SELECT {_PUBLIC} FROM snmp_profiles ORDER BY name").fetchall()
        return [self._public(row) or {} for row in rows]

    def get(self, profile_id: str, *, include_secrets: bool = False) -> dict[str, Any] | None:
        with self._connection_scope() as connection:
            self.ensure_schema(connection)
            row = connection.execute("SELECT * FROM snmp_profiles WHERE id=?", (profile_id,)).fetchone()
        result = row_to_dict(row)
        if result and include_secrets:
            secrets = vault.load(str(result.get("secret_ref") or ""))
            if not secrets:
                raise vault.SNMPProfileVaultError("Secrets SNMPv3 absents du coffre DPAPI.")
            result.update(secrets)
        return result

    def create(self, *, name: str, username: str, auth_key: str, priv_key: str = "", auth_protocol: str = "sha256", priv_protocol: str = "aes128", context_name: str = "", port: int = 161) -> dict[str, Any]:
        values = self._validate(name, username, auth_protocol, priv_protocol, context_name, port)
        if values[3] == "aes128" and not priv_key:
            raise ValueError("La clé privacy est requise avec AES-128.")
        profile_id = str(uuid.uuid4())
        secret_ref = vault.store(profile_id, {"auth_key": auth_key, "priv_key": priv_key})
        try:
            with _LOCK, self._connection_scope() as connection:
                self.ensure_schema(connection)
                connection.execute("INSERT INTO snmp_profiles (id,name,username,auth_protocol,priv_protocol,context_name,port,secret_ref) VALUES (?,?,?,?,?,?,?,?)", (profile_id, *values, secret_ref))
                row = connection.execute(f"SELECT {_PUBLIC} FROM snmp_profiles WHERE id=?", (profile_id,)).fetchone()
        except BaseException:
            vault.delete(secret_ref)
            raise
        return self._public(row) or {}

    def delete(self, profile_id: str) -> None:
        with _LOCK:
            with self._connection_scope() as connection:
                self.ensure_schema(connection)
                row = connection.execute("SELECT secret_ref FROM snmp_profiles WHERE id=?", (profile_id,)).fetchone()
                if row is None:
                    return
                linked = connection.execute("SELECT COUNT(*) FROM network_devices WHERE snmp_profile_id=?", (profile_id,)).fetchone()[0]
                if linked:
                    raise ValueError("Ce profil SNMPv3 est encore lié à un actif.")
                connection.execute("DELETE FROM snmp_profiles WHERE id=?", (profile_id,))
            vault.delete(str(row[0]))

    def set_test_result(self, profile_id: str, ok: bool) -> None:
        with self._connection_scope() as connection:
            connection.execute("UPDATE snmp_profiles SET last_test_ok=?,last_test_at=datetime('now') WHERE id=?", (1 if ok else 0, profile_id))


repository = SNMPProfileRepository()
