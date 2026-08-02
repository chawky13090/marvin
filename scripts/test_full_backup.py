"""Contrats du bundle global chiffré et de sa restauration isolée."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import full_backup


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE proof(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO proof(value) VALUES ('verified')")
        connection.commit()
    finally:
        connection.close()


def test_roundtrip_and_inventory_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-full-backup-") as directory:
        root = Path(directory)
        data = root / "data"
        backups = data / "backups"
        data.mkdir()
        backups.mkdir()
        database = data / "secretary.db"
        _database(database)
        (data / "truth_ledger.jsonl").write_text('{"proof":true}\n', encoding="utf-8")
        lifecycle = data / "windows_secrets.metadata.json"
        lifecycle.write_text(
            '{"schema":1,"secrets":{}}\n',
            encoding="utf-8",
        )
        skill = data / "skills" / "network.md"
        skill.parent.mkdir()
        skill.write_text("# Network", encoding="utf-8")
        maintenance = data / "maintenance" / "sqlite-maintenance-proof.json"
        maintenance.parent.mkdir()
        maintenance.write_text('{"integrity":"ok"}\n', encoding="utf-8")
        (data / "qdrant").mkdir()
        (data / "qdrant" / "cache.bin").write_bytes(b"rebuildable")
        (data / "cache").mkdir()
        (data / "cache" / "preview.bin").write_bytes(b"rebuildable")
        (data / "install").mkdir()
        (data / "install" / "runtime.json").write_text("{}", encoding="utf-8")
        (data / "model_catalog_watch.json").write_text("{}", encoding="utf-8")
        (data / "user-deliverable.pptx").write_bytes(b"portable-user-artifact")
        skill_backup = data / "skills_backup_20260802-120000" / "network.md"
        skill_backup.parent.mkdir()
        skill_backup.write_text("# Previous Network", encoding="utf-8")
        with (
            patch.object(full_backup, "DATA_DIR", data),
            patch.object(full_backup, "DB_PATH", str(database)),
            patch.object(full_backup, "BACKUP_DIR", backups),
        ):
            result = full_backup.create(event_logger=lambda _event, _attrs: None)
            assert result["success"] is True
            assert result["encrypted"] is True
            assert result["integrity_verified"] is True
            source = backups / result["filename"]
            assert full_backup.list_backups()[0]["filename"] == result["filename"]
            verified = full_backup.verify(
                result["filename"],
                event_logger=lambda _event, _attrs: None,
            )
            assert verified["verified_only"] is True
            assert verified["integrity_verified"] is True
            restored = root / "restored"
            recovery = full_backup.restore_to(source, restored)
            assert recovery["success"] is True
            assert (restored / "skills" / "network.md").read_text(encoding="utf-8") == "# Network"
            assert (restored / "truth_ledger.jsonl").read_text(encoding="utf-8") == '{"proof":true}\n'
            assert (restored / lifecycle.name).read_text(encoding="utf-8") == (
                '{"schema":1,"secrets":{}}\n'
            )
            assert (restored / "maintenance" / maintenance.name).is_file()
            assert (restored / "skills_backup_20260802-120000" / "network.md").is_file()
            assert (restored / "user-deliverable.pptx").read_bytes() == b"portable-user-artifact"
            assert not (restored / "qdrant").exists()
            assert not (restored / "cache").exists()
            assert not (restored / "install").exists()
            assert not (restored / "model_catalog_watch.json").exists()
            connection = sqlite3.connect(restored / "secretary.db")
            try:
                assert connection.execute("SELECT value FROM proof").fetchone()[0] == "verified"
            finally:
                connection.close()

            forged = root / "undeclared.zip"
            full_backup._build_plain_archive(forged)
            with zipfile.ZipFile(forged, "a") as archive:
                archive.writestr("payload/undeclared.txt", b"not-in-manifest")
            try:
                full_backup._validate_plain_archive(forged)
            except full_backup.FullBackupError as exc:
                assert "absent de son manifeste" in str(exc)
            else:
                raise AssertionError(
                    "Un fichier absent du manifeste doit invalider le bundle."
                )

            try:
                full_backup._build_plain_archive(
                    root / "reserved-metadata.zip",
                    manifest_metadata={"entries": []},
                )
            except full_backup.FullBackupError as exc:
                assert "écraser le manifeste" in str(exc)
            else:
                raise AssertionError(
                    "Une métadonnée ne doit pas pouvoir écraser le manifeste."
                )

            (data / "unknown_state.json").write_text("{}", encoding="utf-8")
            try:
                full_backup.create(event_logger=lambda _event, _attrs: None)
            except full_backup.FullBackupError as exc:
                assert "non classifiée" in str(exc)
            else:
                raise AssertionError("Une persistance inconnue doit bloquer le bundle.")


def test_destination_and_cipher_context_are_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-full-restore-") as directory:
        root = Path(directory)
        occupied = root / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("keep", encoding="utf-8")
        try:
            full_backup.restore_to(root / "missing.mrvfull", occupied)
        except full_backup.FullBackupError:
            pass
        else:
            raise AssertionError("Une destination non vide doit être refusée.")
        assert (occupied / "keep.txt").read_text(encoding="utf-8") == "keep"


def main() -> int:
    test_roundtrip_and_inventory_gate()
    test_destination_and_cipher_context_are_closed()
    print("Full Backup OK - inventaire fermé, snapshot, chiffrement et restauration isolée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
