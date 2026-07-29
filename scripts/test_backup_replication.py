"""Contrats de réplication hors stockage local d'un bundle chiffré."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import backup_replication


NAME = "marvin_full_20260729_120000_123456.mrvfull"


def test_copy_idempotency_tamper_and_rotation() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-replication-") as directory:
        root = Path(directory)
        data = root / "source-data"
        external = root / "external"
        data.mkdir()
        external.mkdir()
        source = data / NAME
        source.write_bytes(b"encrypted-bundle")
        events: list[tuple[str, dict]] = []
        with patch.object(backup_replication, "DATA_DIR", data):
            first = backup_replication.replicate(
                source,
                external,
                event_logger=lambda event, attrs: events.append((event, attrs)),
            )
            sidecar_path = external / "MarvinBackups" / f"{NAME}.sha256.json"
            sidecar_path.unlink()
            second = backup_replication.replicate(
                source,
                external,
                event_logger=lambda event, attrs: events.append((event, attrs)),
            )
            assert first["idempotent"] is False
            assert second["idempotent"] is True
            target = external / "MarvinBackups" / NAME
            assert target.read_bytes() == source.read_bytes()
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            assert sidecar["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
            target.write_bytes(b"tampered")
            try:
                backup_replication.replicate(source, external)
            except backup_replication.BackupReplicationError as exc:
                assert "homonyme" in str(exc)
            else:
                raise AssertionError("Une copie homonyme altérée doit être refusée.")
        assert events[-1][1]["idempotent"] is True


def test_local_destination_is_refused() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-replication-local-") as directory:
        data = Path(directory) / "data"
        nested = data / "backups"
        nested.mkdir(parents=True)
        source = data / NAME
        source.write_bytes(b"encrypted")
        with patch.object(backup_replication, "DATA_DIR", data):
            for destination in (data, nested, data.parent):
                try:
                    backup_replication.replicate(source, destination)
                except backup_replication.BackupReplicationError:
                    pass
                else:
                    raise AssertionError("Une cible locale au data doit être refusée.")


def main() -> int:
    test_copy_idempotency_tamper_and_rotation()
    test_local_destination_is_refused()
    print("Backup Replication OK - SHA-256, idempotence et séparation du stockage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
