"""Rollback hors ligne du registre enrichi d'actifs d'infrastructure."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import socket
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "secretary.db"
MIGRATION_VERSION = 8


def _backend_is_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8005), timeout=0.3):
            return True
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rollback(database: Path, *, confirmed: bool) -> dict[str, object]:
    database = database.resolve()
    if not confirmed:
        raise RuntimeError("Ajoutez --confirmed après avoir arrêté Marvin.")
    if database == DEFAULT_DATABASE.resolve() and _backend_is_listening():
        raise RuntimeError("Le backend écoute encore sur 127.0.0.1:8005; arrêtez Marvin.")
    if not database.is_file():
        raise FileNotFoundError(database)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = database.with_name(f"{database.name}.pre-asset-registry-rollback-{stamp}")
    source_hash = _sha256(database)
    shutil.copy2(database, backup)
    if _sha256(backup) != source_hash:
        raise RuntimeError("La sauvegarde pré-rollback ne correspond pas à la base source.")

    committed = False
    try:
        with closing(sqlite3.connect(database)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Base invalide avant rollback.")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE network_devices_v7 (
                    id TEXT PRIMARY KEY,
                    ip TEXT NOT NULL,
                    mac TEXT DEFAULT '',
                    hostname TEXT DEFAULT '',
                    custom_name TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(mac, ip)
                )"""
            )
            connection.execute(
                """INSERT INTO network_devices_v7
                   (id,ip,mac,hostname,custom_name,notes,first_seen,last_seen)
                   SELECT id,ip,mac,hostname,custom_name,notes,first_seen,last_seen
                   FROM network_devices"""
            )
            connection.execute("DROP TABLE network_devices")
            connection.execute("ALTER TABLE network_devices_v7 RENAME TO network_devices")
            connection.execute(
                "CREATE INDEX idx_network_devices_last_seen ON network_devices(last_seen DESC)"
            )
            connection.execute(
                "DELETE FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION,)
            )
            connection.execute(f"PRAGMA user_version = {MIGRATION_VERSION - 1}")
            connection.commit()
            committed = True
        with closing(sqlite3.connect(database)) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Base invalide après rollback.")
            columns = {
                row[1] for row in verification.execute("PRAGMA table_info(network_devices)")
            }
            if "asset_type" in columns or "management_protocols" in columns:
                raise RuntimeError("Le schéma enrichi subsiste après rollback.")
    except Exception:
        if committed:
            shutil.copy2(backup, database)
            if _sha256(database) != source_hash:
                raise RuntimeError("La compensation du rollback SQLite a échoué.")
        raise
    return {
        "database": str(database),
        "backup": str(backup),
        "backup_sha256": source_hash,
        "schema_version": MIGRATION_VERSION - 1,
        "integrity_check": "ok",
        "warning": "Les métadonnées enrichies restent récupérables dans la sauvegarde pré-rollback.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()
    print(rollback(args.database, confirmed=args.confirmed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
