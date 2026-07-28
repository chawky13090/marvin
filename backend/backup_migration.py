"""Migration explicite et réversible des sauvegardes SQLite historiques."""
from __future__ import annotations
import hashlib
import hmac
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from backup_encryption import decrypt_file, encrypt_file


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_database(path: Path) -> None:
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("La sauvegarde SQLite est invalide.")
    finally:
        connection.close()


def _validate_sidecar(path: Path) -> None:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not sidecar.exists():
        return
    fields = sidecar.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or fields[1] != path.name or not hmac.compare_digest(fields[0], _sha256(path)):
        raise ValueError("Le manifeste SHA-256 historique est invalide.")


def _write_sidecar(path: Path) -> None:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    temporary = sidecar.with_name(f".{sidecar.name}.{uuid.uuid4().hex}.partial")
    try:
        with temporary.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(f"{_sha256(path)}  {path.name}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, sidecar)
    finally:
        temporary.unlink(missing_ok=True)


def migrate_directory(backup_dir: Path, *, direction: str, apply: bool) -> dict[str, Any]:
    if direction not in {"up", "down"}:
        raise ValueError("direction doit valoir up ou down.")
    backup_dir = backup_dir.resolve()
    if not backup_dir.is_dir():
        raise FileNotFoundError("Le dossier de sauvegarde est introuvable.")
    source_suffix, target_suffix = ((".db", ".mrvbak") if direction == "up" else (".mrvbak", ".db"))
    sources = sorted(backup_dir.glob(f"secretary_*{source_suffix}"))
    result: dict[str, Any] = {"direction": direction, "apply": apply, "found": len(sources), "migrated": 0, "verified": 0, "skipped": 0}
    for source in sources:
        target = source.with_suffix(target_suffix)
        if target.exists():
            raise FileExistsError("Une cible existe déjà; aucune source conflictuelle n'a été supprimée.")
        if not apply:
            result["skipped"] += 1
            continue
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
        verification = backup_dir / f".migration-verify.{uuid.uuid4().hex}.db"
        try:
            if direction == "up":
                _validate_database(source)
                _validate_sidecar(source)
                expected = _sha256(source)
                encrypt_file(source, temporary)
                decrypted = decrypt_file(temporary, verification)
                _validate_database(verification)
                if not hmac.compare_digest(expected, str(decrypted["sha256"])):
                    raise ValueError("La migration chiffrée diffère de la source.")
            else:
                decrypt_file(source, temporary)
                _validate_database(temporary)
            os.replace(temporary, target)
            if direction == "down":
                _write_sidecar(target)
            result["verified"] += 1
            source.unlink()
            if direction == "up":
                source.with_suffix(source.suffix + ".sha256").unlink(missing_ok=True)
            result["migrated"] += 1
        finally:
            verification.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
    return result
