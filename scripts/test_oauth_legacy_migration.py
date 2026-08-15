"""Régression de la migration OAuth SQLite vers le coffre DPAPI."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import dpapi_secret_store
import secret_vault
from db_migrations import MIGRATIONS, apply_migrations
from oauth_legacy_migration import migrate_legacy_tokens, rollback_legacy_tokens


def _legacy_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE oauth_tokens (
            provider TEXT PRIMARY KEY,
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
        (
            (
                "google",
                "legacy-google-access",
                "legacy-google-refresh",
                "Bearer",
                "calendar drive",
                "2030-01-01T00:00:00Z",
            ),
            (
                "microsoft",
                "legacy-ms-access",
                "legacy-ms-refresh",
                "Bearer",
                "Mail.Read",
                "2030-01-02T00:00:00Z",
            ),
        ),
    )
    connection.commit()
    return connection


def main() -> int:
    route_contracts = {
        ROOT / "app/api/auth/google/route.js": "/api/oauth/google/connect",
        ROOT / "app/api/auth/microsoft/route.js": "/api/oauth/microsoft/start",
        ROOT / "app/api/auth/google/callback/route.js": "status: 410",
        ROOT / "app/api/auth/microsoft/callback/route.js": "status: 410",
    }
    for path, marker in route_contracts.items():
        source = path.read_text(encoding="utf-8")
        assert marker in source
        assert "gmailService" not in source
        assert "outlookService" not in source
        assert "access_token" not in source
        assert "refresh_token" not in source
    assert not (ROOT / "lib/services/gmailService.js").exists()
    assert not (ROOT / "lib/services/outlookService.js").exists()

    with tempfile.TemporaryDirectory(prefix="marvin-oauth-migration-") as directory:
        root = Path(directory)
        original_path = dpapi_secret_store.PATH
        dpapi_secret_store.PATH = root / "secrets.dpapi.json"
        connection = _legacy_connection(root / "secretary.db")
        cleanup = (
            ("oauthlegacy", "google", "access"),
            ("oauthlegacy", "google", "refresh"),
            ("oauthlegacy", "microsoft", "access"),
            ("oauthlegacy", "microsoft", "refresh"),
            ("credential", "google_access_token", "value"),
            ("credential", "google_refresh_token", "value"),
            ("credential", "ms_access_token", "value"),
            ("credential", "ms_refresh_token", "value"),
        )
        try:
            try:
                rollback_legacy_tokens(connection, confirmed=False)
            except ValueError:
                pass
            else:
                raise AssertionError("Le rollback OAuth sans confirmation devait être refusé.")
            secret_vault.set_secret(
                "credential",
                "google_access_token",
                "value",
                "current-google-access",
            )
            assert migrate_legacy_tokens(connection) == 2
            connection.commit()
            assert connection.execute("SELECT COUNT(*) FROM oauth_tokens").fetchone()[0] == 0
            assert (
                secret_vault.get_secret("credential", "google_access_token", "value")
                == "current-google-access"
            )
            assert (
                secret_vault.get_secret("credential", "ms_access_token", "value")
                == "legacy-ms-access"
            )
            assert apply_migrations(connection, MIGRATIONS) == [1, 2, 3, 4, 5, 6, 7]
            connection.commit()
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(oauth_tokens)")
            }
            assert columns == {
                "provider",
                "token_type",
                "scope",
                "expires_at",
                "migrated_at",
            }
            ciphertext = dpapi_secret_store.PATH.read_text(encoding="utf-8")
            assert "legacy-google-access" not in ciphertext
            assert "legacy-ms-refresh" not in ciphertext

            assert rollback_legacy_tokens(connection, confirmed=True) == 2
            restored = connection.execute(
                """SELECT provider,access_token,refresh_token
                   FROM oauth_tokens ORDER BY provider"""
            ).fetchall()
            assert restored == [
                ("google", "legacy-google-access", "legacy-google-refresh"),
                ("microsoft", "legacy-ms-access", "legacy-ms-refresh"),
            ]
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
            assert connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version=6"
            ).fetchone() is None
            assert secret_vault.get_secret("oauthlegacy", "google", "access") is None
        finally:
            connection.close()
            for scope, owner, field in cleanup:
                secret_vault.delete_secret(scope, owner, field)
            dpapi_secret_store.PATH = original_path
    print("Migration OAuth OK - DPAPI, priorité, tombstone et rollback exact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
