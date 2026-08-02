"""Contrats d'export Marvin portable, sans secrets DPAPI."""

from __future__ import annotations

import json
import sqlite3
import struct
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import full_backup
import portable_backup
from portable_backup_encryption import PortableEncryptionError


PASSPHRASE = "phrase de test portable assez longue"


def _database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE proof(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO proof(value) VALUES ('portable')")
        connection.commit()
    finally:
        connection.close()


def test_roundtrip_excludes_machine_bound_secrets() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-portable-") as directory:
        root = Path(directory)
        data = root / "data"
        data.mkdir()
        database = data / "secretary.db"
        _database(database)
        (data / "truth_ledger.jsonl").write_text('{"proof":true}\n', encoding="utf-8")
        (data / "windows_secrets.dpapi.json").write_text("ciphertext", encoding="utf-8")
        (data / "windows_secrets.metadata.json").write_text(
            '{"schema":1,"secrets":{"oauth":{"category":"oauth"}}}',
            encoding="utf-8",
        )
        bundle = root / "marvin-export.mrvportable"
        with (
            patch.object(full_backup, "DATA_DIR", data),
            patch.object(full_backup, "DB_PATH", str(database)),
        ):
            created = portable_backup.create(
                bundle,
                passphrase=PASSPHRASE,
                event_logger=lambda _event, _attributes: None,
            )
        assert created["portable"] is True
        assert created["dpapi_secrets_included"] is False
        assert created["reauthentication_required"] is True
        verified = portable_backup.verify(
            bundle,
            passphrase=PASSPHRASE,
            event_logger=lambda _event, _attributes: None,
        )
        assert verified["verified_only"] is True
        restored = root / "restored"
        result = portable_backup.restore_to(bundle, restored, passphrase=PASSPHRASE)
        assert result["integrity_verified"] is True
        assert not (restored / "windows_secrets.dpapi.json").exists()
        assert not (restored / "windows_secrets.metadata.json").exists()
        assert (restored / "truth_ledger.jsonl").is_file()
        connection = sqlite3.connect(restored / "secretary.db")
        try:
            assert connection.execute("SELECT value FROM proof").fetchone()[0] == "portable"
        finally:
            connection.close()


def test_wrong_passphrase_tamper_and_destination_guards() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-portable-negative-") as directory:
        root = Path(directory)
        data = root / "data"
        data.mkdir()
        database = data / "secretary.db"
        _database(database)
        bundle = root / "marvin-export.mrvportable"
        try:
            with (
                patch.object(full_backup, "DATA_DIR", data),
                patch.object(full_backup, "DB_PATH", str(database)),
            ):
                portable_backup.create(
                    bundle,
                    passphrase="trop courte",
                    event_logger=lambda _event, _attributes: None,
                )
        except PortableEncryptionError:
            pass
        else:
            raise AssertionError("Une phrase secrète trop courte doit être refusée.")
        assert not bundle.exists()
        with (
            patch.object(full_backup, "DATA_DIR", data),
            patch.object(full_backup, "DB_PATH", str(database)),
        ):
            portable_backup.create(
                bundle,
                passphrase=PASSPHRASE,
                event_logger=lambda _event, _attributes: None,
            )
        try:
            portable_backup.verify(
                bundle,
                passphrase="phrase incorrecte mais longue",
                event_logger=lambda _event, _attributes: None,
            )
        except PortableEncryptionError:
            pass
        else:
            raise AssertionError("Une phrase secrète incorrecte doit être refusée.")
        tampered = root / "tampered.mrvportable"
        payload = bytearray(bundle.read_bytes())
        payload[-17] ^= 0x01
        tampered.write_bytes(payload)
        try:
            portable_backup.verify(
                tampered,
                passphrase=PASSPHRASE,
                event_logger=lambda _event, _attributes: None,
            )
        except PortableEncryptionError:
            pass
        else:
            raise AssertionError("Un bundle altéré doit être refusé.")
        parameter_tampered = root / "parameter-tampered.mrvportable"
        parameter_payload = bytearray(bundle.read_bytes())
        header_start = 12
        header_length = struct.unpack(">I", parameter_payload[8:12])[0]
        header = json.loads(parameter_payload[header_start:header_start + header_length])
        header["n"] += 1
        replacement = json.dumps(
            header,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert len(replacement) == header_length
        parameter_payload[header_start:header_start + header_length] = replacement
        parameter_tampered.write_bytes(parameter_payload)
        try:
            portable_backup.verify(
                parameter_tampered,
                passphrase=PASSPHRASE,
                event_logger=lambda _event, _attributes: None,
            )
        except PortableEncryptionError as exc:
            assert "dérivation" in str(exc)
        else:
            raise AssertionError("Des paramètres KDF modifiés doivent être refusés.")
        occupied = root / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("keep", encoding="utf-8")
        try:
            portable_backup.restore_to(bundle, occupied, passphrase=PASSPHRASE)
        except full_backup.FullBackupError:
            pass
        else:
            raise AssertionError("Une destination non vide doit être refusée.")
        assert (occupied / "keep.txt").read_text(encoding="utf-8") == "keep"

        oversized = root / "oversized.mrvportable"
        oversized.touch()
        oversized.write_bytes(b"x")
        with patch.object(
            portable_backup,
            "MAX_ENCRYPTED_BYTES",
            0,
        ):
            try:
                portable_backup.restore_to(
                    oversized,
                    root / "oversized-restore",
                    passphrase=PASSPHRASE,
                )
            except portable_backup.PortableBackupError as exc:
                assert "taille" in str(exc)
            else:
                raise AssertionError("Un bundle hors limite doit être refusé avant lecture.")


def main() -> int:
    test_roundtrip_excludes_machine_bound_secrets()
    test_wrong_passphrase_tamper_and_destination_guards()
    print("Portable Backup OK - scrypt, AES-GCM, intégrité et exclusion DPAPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
