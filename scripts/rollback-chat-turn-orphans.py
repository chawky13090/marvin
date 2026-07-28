"""Rollback de données SEC-014; à exécuter uniquement avec Marvin arrêté."""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from chat_turn_integrity import integrity_summary, restore_archived_orphans
from config import DB_PATH


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--accept-invalid-state", action="store_true")
    args = parser.parse_args()
    connection = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        if not args.apply:
            print(json.dumps(integrity_summary(connection), sort_keys=True))
            return 0
        if not args.accept_invalid_state:
            raise SystemExit("--accept-invalid-state est obligatoire.")
        print(json.dumps(
            restore_archived_orphans(connection, confirmed=True),
            sort_keys=True,
        ))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
