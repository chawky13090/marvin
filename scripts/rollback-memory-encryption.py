"""Rollback hors ligne du chiffrement actif des souvenirs Marvin."""

from __future__ import annotations

import argparse
import socket
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import DB_PATH, QDRANT_PATH
from db_connection import db
from repositories.memories import repository
import vector_store


def _backend_is_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", 8005)) == 0


def _snapshot_database(source: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    destination = source.with_name(f"{source.stem}.pre-memory-rollback.{stamp}.db")
    with sqlite3.connect(source) as current, sqlite3.connect(destination) as snapshot:
        current.backup(snapshot)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()
    if not args.confirmed:
        raise SystemExit("Ajoutez --confirmed après avoir arrêté Marvin.")
    if _backend_is_running():
        raise SystemExit("Rollback refusé : le backend Marvin écoute encore sur le port 8005.")
    database_path = Path(DB_PATH)
    if not database_path.is_file():
        raise SystemExit("Base SQLite Marvin absente.")
    snapshot = _snapshot_database(database_path)
    with db(database_path) as connection:
        sqlite_count = repository.rollback_encryption(connection)
    qdrant_count = 0
    if Path(QDRANT_PATH).exists() and vector_store._qdrant_available:
        client = vector_store.QdrantClient(path=QDRANT_PATH)
        try:
            qdrant_count = vector_store.rollback_memory_payload_protection(client)
        finally:
            client.close()
    print(
        f"Rollback mémoire terminé : SQLite={sqlite_count}, "
        f"Qdrant={qdrant_count}, sauvegarde={snapshot.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
