"""Rollback hors ligne du champ d'archivage des conversations.

Marvin doit être arrêté. Le script restaure d'abord toutes les conversations,
crée une copie de la base, puis retire l'index et la colonne ajoutés.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "secretary.db"


def rollback_database(database: Path) -> Path:
    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Base introuvable: {database}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = database.with_name(f"{database.name}.pre-archive-rollback-{timestamp}.bak")
    shutil.copy2(database, backup)

    connection = sqlite3.connect(database)
    try:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "archived_at" not in columns:
            return backup
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE conversations SET archived_at = NULL")
        connection.execute("DROP INDEX IF EXISTS idx_conversations_archived_updated")
        connection.execute("ALTER TABLE conversations DROP COLUMN archived_at")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("PRAGMA quick_check a échoué.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit("Rollback refusé sans --confirm.")
    backup = rollback_database(args.database)
    print(f"Rollback réussi. Sauvegarde: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
