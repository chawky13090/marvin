"""Migration réversible de l'ancien stockage OAuth SQLite vers DPAPI."""
from __future__ import annotations

import hmac
import sqlite3
from typing import Any

import secret_vault


_PROVIDERS = {
    "google": ("google_access_token", "google_refresh_token"),
    "microsoft": ("ms_access_token", "ms_refresh_token"),
}
_MAX_TOKEN = 16_384


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(oauth_tokens)").fetchall()
    }


def migrate_legacy_tokens(connection: sqlite3.Connection) -> int:
    """Copie, relit puis efface les jetons en clair; commit laissé à l'appelant."""
    columns = _columns(connection)
    if "access_token" not in columns:
        return 0
    connection.execute(
        """CREATE TABLE IF NOT EXISTS oauth_token_migration_metadata (
            provider TEXT PRIMARY KEY,
            token_type TEXT,
            scope TEXT,
            expires_at TEXT,
            migrated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    rows = connection.execute(
        """SELECT provider,access_token,refresh_token,token_type,scope,expires_at
           FROM oauth_tokens ORDER BY provider"""
    ).fetchall()
    if len(rows) > len(_PROVIDERS):
        raise ValueError("Nombre de fournisseurs OAuth historiques invalide.")
    written: list[tuple[str, str, str]] = []
    try:
        for row in rows:
            provider = str(row[0])
            if provider not in _PROVIDERS:
                raise ValueError("Fournisseur OAuth historique inconnu.")
            access = row[1]
            refresh = row[2]
            if not isinstance(access, str) or not access or len(access) > _MAX_TOKEN:
                raise ValueError("Jeton OAuth historique invalide.")
            if refresh is not None and (
                not isinstance(refresh, str) or len(refresh) > _MAX_TOKEN
            ):
                raise ValueError("Jeton OAuth historique invalide.")
            # Copie dédiée uniquement au rollback de la migration.
            secret_vault.set_secret("oauthlegacy", provider, "access", access)
            written.append(("oauthlegacy", provider, "access"))
            if refresh:
                secret_vault.set_secret("oauthlegacy", provider, "refresh", refresh)
                written.append(("oauthlegacy", provider, "refresh"))
            access_name, refresh_name = _PROVIDERS[provider]
            if not secret_vault.has_secret("credential", access_name, "value"):
                secret_vault.set_secret("credential", access_name, "value", access)
                written.append(("credential", access_name, "value"))
            if refresh and not secret_vault.has_secret(
                "credential", refresh_name, "value"
            ):
                secret_vault.set_secret(
                    "credential", refresh_name, "value", refresh
                )
                written.append(("credential", refresh_name, "value"))
            recovered = secret_vault.get_secret(
                "oauthlegacy", provider, "access"
            )
            if recovered is None or not hmac.compare_digest(recovered, access):
                raise RuntimeError("Relecture OAuth DPAPI incohérente.")
            connection.execute(
                """INSERT INTO oauth_token_migration_metadata
                   (provider,token_type,scope,expires_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(provider) DO UPDATE SET
                     token_type=excluded.token_type,
                     scope=excluded.scope,
                     expires_at=excluded.expires_at,
                     migrated_at=datetime('now')""",
                (provider, row[3], row[4], row[5]),
            )
        connection.execute("DELETE FROM oauth_tokens")
        if connection.execute("SELECT COUNT(*) FROM oauth_tokens").fetchone()[0]:
            raise RuntimeError("Le nettoyage OAuth SQLite a échoué.")
        return len(rows)
    except BaseException:
        for scope, owner, field in reversed(written):
            secret_vault.delete_secret(scope, owner, field)
        raise


def rollback_legacy_tokens(
    connection: sqlite3.Connection, *, confirmed: bool
) -> int:
    if confirmed is not True:
        raise ValueError("Confirmation explicite requise.")
    metadata = connection.execute(
        """SELECT provider,token_type,scope,expires_at
           FROM oauth_tokens ORDER BY provider"""
    ).fetchall()
    restored: list[tuple[Any, ...]] = []
    for row in metadata:
        provider = str(row[0])
        if provider not in _PROVIDERS:
            raise ValueError("Fournisseur OAuth tombstone inconnu.")
        access = secret_vault.get_secret("oauthlegacy", provider, "access")
        refresh = secret_vault.get_secret("oauthlegacy", provider, "refresh")
        if not access:
            raise RuntimeError("Copie OAuth de rollback absente.")
        restored.append((provider, access, refresh, row[1], row[2], row[3]))
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("DROP TABLE oauth_tokens")
        connection.execute(
            """CREATE TABLE oauth_tokens (
                provider TEXT PRIMARY KEY
                    CHECK(provider IN ('google','microsoft')),
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_type TEXT DEFAULT 'Bearer',
                scope TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.executemany(
            """INSERT INTO oauth_tokens
               (provider,access_token,refresh_token,token_type,scope,expires_at)
               VALUES (?,?,?,?,?,?)""",
            restored,
        )
        connection.execute(
            "DELETE FROM schema_migrations WHERE version=6"
        )
        connection.execute("PRAGMA user_version=5")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    for provider, *_ in restored:
        secret_vault.delete_secret("oauthlegacy", provider, "access")
        secret_vault.delete_secret("oauthlegacy", provider, "refresh")
    return len(restored)
