"""Rollback hors ligne des colonnes de telemetrie locale des executions d'outils."""

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
TELEMETRY_COLUMNS = (
    "tool_call_id",
    "app_version",
    "model_name",
    "runtime_mode",
    "profile_name",
    "selector_version",
    "candidate_count",
    "candidate_set_sha256",
    "execution_source",
    "canonicalized_from",
)


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
    backup = database.with_name(f"{database.name}.pre-telemetry-rollback-{stamp}")
    source_hash = _sha256(database)
    shutil.copy2(database, backup)
    before_hash = _sha256(backup)
    if before_hash != source_hash:
        raise RuntimeError("La sauvegarde pre-rollback ne correspond pas a la base source.")

    removed: list[str] = []
    committed = False
    try:
        with closing(sqlite3.connect(database)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Base invalide avant rollback: {integrity}")
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(tool_executions)")
            }
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP INDEX IF EXISTS idx_tool_executions_tool_call")
            for name in TELEMETRY_COLUMNS:
                if name in columns:
                    connection.execute(f"ALTER TABLE tool_executions DROP COLUMN {name}")
                    removed.append(name)
            connection.commit()
            committed = True
        with closing(sqlite3.connect(database)) as verification:
            integrity = verification.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Base invalide apres rollback: {integrity}")
    except Exception:
        if committed:
            shutil.copy2(backup, database)
            if _sha256(database) != source_hash:
                raise RuntimeError("La compensation du rollback SQLite a echoue.")
        raise
    return {
        "database": str(database),
        "backup": str(backup),
        "backup_sha256": before_hash,
        "removed_columns": removed,
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
