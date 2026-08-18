"""Descente hors ligne de la migration 9 SNMPv3 avec sauvegarde vérifiée."""
from __future__ import annotations

import argparse
import hashlib
import socket
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "secretary.db"
MIGRATION_VERSION = 9


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


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    """Copie cohérente incluant les pages WAL via l'API SQLite."""
    with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)


def _restore_snapshot(snapshot: Path, destination: Path) -> None:
    with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)


def rollback(database: Path, *, confirmed: bool) -> dict[str, object]:
    database = database.resolve()
    if not confirmed:
        raise RuntimeError("Ajoutez --confirmed après avoir arrêté Marvin.")
    if database == DEFAULT_DATABASE.resolve() and _backend_is_listening():
        raise RuntimeError("Le backend écoute encore sur 127.0.0.1:8005; arrêtez Marvin.")
    if not database.is_file():
        raise FileNotFoundError(database)
    with closing(sqlite3.connect(database)) as check:
        profile_count = check.execute("SELECT COUNT(*) FROM snmp_profiles").fetchone()[0]
    if profile_count:
        raise RuntimeError("Supprimez d'abord les profils SNMPv3 depuis Connexions; leurs secrets DPAPI ne doivent pas être orphelins.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = database.with_name(f"{database.name}.pre-snmpv3-rollback-{stamp}")
    _sqlite_snapshot(database, backup)
    source_hash = _sha256(backup)
    with closing(sqlite3.connect(backup)) as verification:
        if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("La sauvegarde SQLite pré-rollback est invalide.")
    committed = False
    try:
        with closing(sqlite3.connect(database)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Base invalide avant rollback.")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""CREATE TABLE network_devices_v8 (
                id TEXT PRIMARY KEY, ip TEXT NOT NULL, mac TEXT DEFAULT '', hostname TEXT DEFAULT '',
                custom_name TEXT DEFAULT '', notes TEXT DEFAULT '', first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')), asset_type TEXT NOT NULL DEFAULT 'unknown',
                vendor TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', os_family TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '', site TEXT NOT NULL DEFAULT '', management_protocols TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]', ssh_connection_id TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), source TEXT NOT NULL DEFAULT 'discovery',
                updated_at TEXT NOT NULL DEFAULT '', UNIQUE(mac, ip))""")
            connection.execute("""INSERT INTO network_devices_v8
                (id,ip,mac,hostname,custom_name,notes,first_seen,last_seen,asset_type,vendor,model,os_family,role,site,
                 management_protocols,tags,ssh_connection_id,enabled,source,updated_at)
                SELECT id,ip,mac,hostname,custom_name,notes,first_seen,last_seen,asset_type,vendor,model,os_family,role,site,
                       management_protocols,tags,ssh_connection_id,enabled,source,updated_at FROM network_devices""")
            connection.execute("DROP TABLE network_devices")
            connection.execute("ALTER TABLE network_devices_v8 RENAME TO network_devices")
            connection.execute("CREATE INDEX idx_network_devices_last_seen ON network_devices(last_seen DESC)")
            connection.execute("CREATE INDEX idx_network_devices_asset_type ON network_devices(asset_type,enabled)")
            connection.execute("CREATE INDEX idx_network_devices_site ON network_devices(site,enabled)")
            connection.execute("DROP TABLE snmp_profiles")
            connection.execute("DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,))
            connection.execute("PRAGMA user_version=8")
            connection.commit()
            committed = True
        with closing(sqlite3.connect(database)) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Base invalide après rollback.")
            if "snmp_profile_id" in {row[1] for row in verification.execute("PRAGMA table_info(network_devices)")}:
                raise RuntimeError("La colonne SNMPv3 subsiste après rollback.")
    except Exception:
        if committed:
            _restore_snapshot(backup, database)
            with closing(sqlite3.connect(database)) as compensation:
                if compensation.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("La compensation du rollback SQLite a échoué.")
        raise
    return {"database": str(database), "backup": str(backup), "backup_sha256": source_hash, "schema_version": 8, "integrity_check": "ok"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()
    print(rollback(args.database, confirmed=args.confirmed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
