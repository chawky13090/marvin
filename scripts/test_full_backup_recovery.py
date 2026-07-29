"""Contrats de l'application hors ligne et de sa compensation."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import full_backup
import full_backup_recovery


def _write_database(path: Path, value: str) -> None:
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE proof(value TEXT NOT NULL)")
        connection.execute("INSERT INTO proof(value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _read_database(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return str(connection.execute("SELECT value FROM proof").fetchone()[0])
    finally:
        connection.close()


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    data = root / "data"
    backups = data / "backups"
    data.mkdir()
    backups.mkdir()
    database = data / "secretary.db"
    _write_database(database, "bundle")
    document = data / "documents" / "kept.txt"
    document.parent.mkdir()
    document.write_text("bundle", encoding="utf-8")
    with (
        patch.object(full_backup, "DATA_DIR", data),
        patch.object(full_backup, "DB_PATH", str(database)),
        patch.object(full_backup, "BACKUP_DIR", backups),
    ):
        created = full_backup.create(event_logger=lambda _event, _attrs: None)
    return data, database, backups / created["filename"]


def test_apply_preserves_machine_state() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-full-apply-") as directory:
        data, database, source = _fixture(Path(directory))
        _write_database(database, "current")
        (data / "documents" / "current-only.txt").write_text("remove", encoding="utf-8")
        (data / "qdrant").mkdir()
        (data / "qdrant" / "projection.bin").write_bytes(b"preserve")
        reconciliations: list[str] = []

        result = full_backup_recovery.apply_offline(
            source,
            target_data=data,
            reconcile=lambda: reconciliations.append("ok") or {"success": True},
            create_backup=lambda: {"success": True, "filename": "pre-restore.mrvfull"},
            event_logger=lambda _event, _attrs: None,
        )

        assert result["success"] is True
        assert result["pre_restore_filename"] == "pre-restore.mrvfull"
        assert _read_database(database) == "bundle"
        assert (data / "documents" / "kept.txt").read_text(encoding="utf-8") == "bundle"
        assert not (data / "documents" / "current-only.txt").exists()
        assert (data / "qdrant" / "projection.bin").read_bytes() == b"preserve"
        assert reconciliations == ["ok"]
        assert not list(data.parent.glob(".marvin-restore-*"))


def test_reconciliation_failure_compensates() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-full-compensate-") as directory:
        data, database, source = _fixture(Path(directory))
        _write_database(database, "current")
        current_only = data / "documents" / "current-only.txt"
        current_only.write_text("preserved", encoding="utf-8")
        calls = 0

        def reconcile() -> dict[str, bool]:
            nonlocal calls
            calls += 1
            return {"success": calls > 1}

        try:
            full_backup_recovery.apply_offline(
                source,
                target_data=data,
                reconcile=reconcile,
                create_backup=lambda: {
                    "success": True,
                    "filename": "pre-restore.mrvfull",
                },
                event_logger=lambda _event, _attrs: None,
            )
        except full_backup_recovery.FullRecoveryError:
            pass
        else:
            raise AssertionError("Une réconciliation refusée doit faire échouer l'application.")

        assert calls == 2
        assert _read_database(database) == "current"
        assert current_only.read_text(encoding="utf-8") == "preserved"
        assert not list(data.parent.glob(".marvin-restore-*"))


def main() -> int:
    test_apply_preserves_machine_state()
    test_reconciliation_failure_compensates()
    print("Full Recovery OK - application hors ligne, projection et compensation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
