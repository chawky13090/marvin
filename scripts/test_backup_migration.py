"""Régressions de migration chiffrée et rollback des sauvegardes."""
from __future__ import annotations
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from backup_migration import migrate_directory


def _database(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE state(value TEXT NOT NULL)")
        connection.execute("INSERT INTO state VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _value(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT value FROM state").fetchone()[0]
    finally:
        connection.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "secretary_20260728_120000.db"
        _database(source, "preuve")
        assert migrate_directory(root, direction="up", apply=False)["skipped"] == 1
        up = migrate_directory(root, direction="up", apply=True)
        encrypted = source.with_suffix(".mrvbak")
        assert up["migrated"] == up["verified"] == 1
        assert encrypted.exists() and not source.exists()
        down = migrate_directory(root, direction="down", apply=True)
        assert down["migrated"] == down["verified"] == 1
        assert _value(source) == "preuve"
        assert source.with_suffix(".db.sha256").is_file()
        encrypted.write_bytes(b"collision")
        try:
            migrate_directory(root, direction="up", apply=True)
        except FileExistsError:
            pass
        else:
            raise AssertionError("Une collision de migration doit être refusée.")
        assert source.exists() and encrypted.read_bytes() == b"collision"
    print("Backup Migration OK - dry-run, montée, descente et collision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
