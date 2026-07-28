"""Régressions réelles de sauvegarde et restauration SQLite."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from backup import BackupService


NOW = datetime(2026, 7, 28, 18, 30, 0, 123456, tzinfo=timezone.utc)


def _write_value(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS state (value TEXT NOT NULL)"
        )
        connection.execute("DELETE FROM state")
        connection.execute("INSERT INTO state(value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _read_value(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT value FROM state").fetchone()[0]
    finally:
        connection.close()


def main() -> int:
    events: list[tuple[str, dict]] = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "secretary.db"
        backups = root / "backups"
        _write_value(database, "initial")
        service = BackupService(
            database,
            backups,
            keep_last=20,
            clock=lambda: NOW,
            event_logger=lambda event, attrs: events.append((event, attrs)),
        )

        first = service.create()
        assert first["success"] is True
        assert first["integrity_verified"] is True
        assert first["foreign_key_violations"] == 0
        assert len(first["sha256"]) == 64
        assert Path(first["path"]).is_file()
        assert Path(first["path"] + ".sha256").is_file()

        _write_value(database, "courant")
        restored = service.restore(first["filename"])
        assert restored["success"] is True
        assert restored["checksum_verified"] is True
        assert restored["integrity_verified"] is True
        assert restored["foreign_key_violations"] == 0
        assert restored["compensated"] is False
        assert _read_value(database) == "initial"
        assert Path(restored["pre_restore_backup"]).is_file()
        assert service.list()[0]["checksum_available"] is True

        legacy = backups / "secretary_20260728_120000.db"
        source = sqlite3.connect(database)
        destination = sqlite3.connect(legacy)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        _write_value(database, "avant-legacy")
        legacy_result = service.restore(legacy.name)
        assert legacy_result["success"] is True
        assert legacy_result["checksum_verified"] is False
        assert _read_value(database) == "initial"

        tampered = service.create()
        sidecar = Path(tampered["path"] + ".sha256")
        sidecar.write_text(
            f"{'0' * 64}  {tampered['filename']}\n",
            encoding="ascii",
        )
        _write_value(database, "avant-rejet")
        rejected = service.restore(tampered["filename"])
        assert rejected["success"] is False
        assert rejected["error_code"] == "invalid_backup"
        assert rejected["compensated"] is False
        assert _read_value(database) == "avant-rejet"
        assert str(root) not in rejected["error"]

        corrupted = backups / "secretary_20260728_130000.db"
        corrupted.write_bytes(b"not-sqlite")
        corrupt_result = service.restore(corrupted.name)
        assert corrupt_result["success"] is False
        assert corrupt_result["error_code"] == "invalid_backup"
        assert _read_value(database) == "avant-rejet"

        valid = service.create()
        _write_value(database, "etat-a-preserver")
        original_restore = service._restore_from
        calls = 0

        def fail_after_mutation(source_path: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                _write_value(database, "etat-partiel")
                raise sqlite3.OperationalError("failure with private path")
            original_restore(source_path)

        service._restore_from = fail_after_mutation
        compensated = service.restore(valid["filename"])
        service._restore_from = original_restore
        assert compensated["success"] is False
        assert compensated["error_code"] == "restore_failed"
        assert compensated["compensated"] is True
        assert _read_value(database) == "etat-a-preserver"
        assert str(root) not in compensated["error"]

        missing = service.restore("secretary_20260728_140000.db")
        assert missing["error_code"] == "backup_not_found"
        invalid = service.restore("../secretary_20260728_140000.db")
        assert invalid["error_code"] == "invalid_backup"

        concurrent_root = root / "concurrent"
        concurrent = BackupService(
            database,
            concurrent_root,
            keep_last=20,
            clock=lambda: NOW,
            event_logger=lambda *_: None,
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: concurrent.create(), range(8)))
        assert all(result["success"] for result in results)
        assert len({result["filename"] for result in results}) == 8
        assert len(concurrent.list()) == 8

        rotating = BackupService(
            database,
            root / "rotating",
            keep_last=2,
            clock=lambda: NOW,
            event_logger=lambda *_: None,
        )
        rotation_results = [rotating.create() for _ in range(4)]
        assert all(result["success"] for result in rotation_results)
        assert len(rotating.list()) == 2
        assert len(list((root / "rotating").glob("*.sha256"))) == 2
        assert not list((root / "rotating").glob("*.partial"))

        absent = BackupService(
            root / "absent.db",
            root / "absent-backups",
            event_logger=lambda *_: None,
        ).create()
        assert absent["success"] is False
        assert absent["error_code"] == "FileNotFoundError"
        assert str(root) not in absent["error"]

        fk_database = root / "legacy-fk.db"
        connection = sqlite3.connect(fk_database)
        try:
            connection.executescript(
                """PRAGMA foreign_keys=OFF;
                   CREATE TABLE parent(id INTEGER PRIMARY KEY);
                   CREATE TABLE child(
                       parent_id INTEGER REFERENCES parent(id)
                   );
                   INSERT INTO child(parent_id) VALUES (99);"""
            )
            connection.commit()
        finally:
            connection.close()
        fk_service = BackupService(
            fk_database,
            root / "legacy-fk-backups",
            event_logger=lambda *_: None,
        )
        fk_backup = fk_service.create()
        assert fk_backup["success"] is True
        assert fk_backup["integrity_verified"] is True
        assert fk_backup["foreign_key_violations"] == 1

    assert any(event == "database_backup" for event, _ in events)
    assert any(event == "database_restore" for event, _ in events)
    assert all(
        all("path" not in key for key in attributes)
        for _, attributes in events
        for key in attributes
    )
    worker_source = (BACKEND / "runtime_workers.py").read_text(
        encoding="utf-8"
    )
    worker_block = worker_source[
        worker_source.index("async def database_backup_worker")
        : worker_source.index("async def memory_consolidation_worker")
    ]
    assert "result['path']" not in worker_block
    assert "str(exc)" not in worker_block

    import backup
    from api import backups as backup_api

    assert backup.create_backup.__self__ is backup.service
    assert backup.restore_backup.__self__ is backup.service
    assert backup.list_backups.__self__ is backup.service
    try:
        backup_api.RestoreRequest(
            filename="../secretary_20260728_120000.db",
            confirmed=True,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Le chemin hostile doit être refusé par l'API.")
    try:
        backup_api.RestoreRequest(
            filename="secretary_20260728_120000.db",
            confirmed=1,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("La confirmation API doit être strictement booléenne.")

    original = backup.restore_backup
    try:
        backup.restore_backup = lambda _filename: {
            "success": False,
            "error": "La sauvegarde est invalide ou corrompue.",
            "error_code": "invalid_backup",
        }
        try:
            asyncio.run(
                backup_api.restore_backup_now(
                    backup_api.RestoreRequest(
                        filename="secretary_20260728_120000.db",
                        confirmed=True,
                    )
                )
            )
        except backup_api.HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Une sauvegarde corrompue doit produire HTTP 409.")
    finally:
        backup.restore_backup = original

    print(
        "Backup Service OK - snapshot, SHA-256, intégrité, legacy, "
        "compensation, concurrence, rotation, API et erreurs expurgées."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
