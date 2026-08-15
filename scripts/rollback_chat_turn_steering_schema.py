"""Rollback hors ligne du schema de pilotage des tours de chat."""

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
TABLES = ("chat_turn_directives", "chat_turn_slots")
MIGRATION_VERSION = 7


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
        raise RuntimeError("Ajoutez --confirmed apres avoir arrete Marvin.")
    if database == DEFAULT_DATABASE.resolve() and _backend_is_listening():
        raise RuntimeError("Le backend ecoute encore sur 127.0.0.1:8005; arretez Marvin.")
    if not database.is_file():
        raise FileNotFoundError(database)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = database.with_name(f"{database.name}.pre-chat-steering-rollback-{stamp}")
    source_hash = _sha256(database)
    shutil.copy2(database, backup)
    if _sha256(backup) != source_hash:
        raise RuntimeError("La sauvegarde pre-rollback ne correspond pas a la base source.")

    committed = False
    try:
        with closing(sqlite3.connect(database)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Base invalide avant rollback.")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP INDEX IF EXISTS idx_chat_turn_directives_status")
            for table in TABLES:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            connection.execute(
                "DELETE FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION,)
            )
            connection.execute(f"PRAGMA user_version = {MIGRATION_VERSION - 1}")
            connection.commit()
            committed = True
        with closing(sqlite3.connect(database)) as verification:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Base invalide apres rollback.")
            remaining = {
                row[0]
                for row in verification.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if set(TABLES) & remaining:
                raise RuntimeError("Le schema de pilotage subsiste apres rollback.")
    except Exception:
        if committed:
            shutil.copy2(backup, database)
            if _sha256(database) != source_hash:
                raise RuntimeError("La compensation du rollback SQLite a echoue.")
        raise
    return {
        "database": str(database),
        "backup": str(backup),
        "backup_sha256": source_hash,
        "removed_tables": list(TABLES),
        "schema_version": MIGRATION_VERSION - 1,
        "integrity_check": "ok",
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
