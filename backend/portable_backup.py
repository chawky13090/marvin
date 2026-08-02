"""Export portable des données Marvin, sans secrets liés à l'identité Windows."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import full_backup
from portable_backup_encryption import decrypt_file, encrypt_file


PORTABLE_EXTENSION = ".mrvportable"
MACHINE_BOUND_SECRET_FILES = frozenset({
    "windows_secrets.dpapi.json",
    "windows_secrets.metadata.json",
})
_LOCK = threading.RLock()
EventLogger = Callable[[str, dict[str, Any]], None]
MAX_ENCRYPTED_BYTES = full_backup.MAX_TOTAL_BYTES + 64 * 1024 * 1024


class PortableBackupError(RuntimeError):
    pass


def _default_event_logger(event: str, attributes: dict[str, Any]) -> None:
    try:
        import audit

        audit.log_action(
            event,
            result={
                "success": bool(attributes.get("success")),
                "files": int(attributes.get("files") or 0),
                "payload_bytes": int(attributes.get("payload_bytes") or 0),
                "error": attributes.get("error_code"),
            },
            source="offline_portable_backup",
        )
    except Exception:
        pass


def _validate_destination(destination: Path) -> Path:
    raw = destination.absolute()
    if raw.suffix.lower() != PORTABLE_EXTENSION:
        raise PortableBackupError(f"La destination doit utiliser {PORTABLE_EXTENSION}.")
    if raw.exists() or raw.is_symlink():
        raise PortableBackupError("La destination existe déjà ou est un lien symbolique.")
    if not raw.parent.is_dir() or raw.parent.is_symlink():
        raise PortableBackupError("Le dossier de destination doit exister sans lien symbolique.")
    return raw


def _extract(archive_path: Path, destination: Path) -> dict[str, Any]:
    if destination.exists() and any(destination.iterdir()):
        raise full_backup.FullBackupError("La destination de restauration doit être vide.")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        manifest = full_backup._validate_plain_archive(archive_path)
        with zipfile.ZipFile(archive_path, "r") as archive:
            for entry in manifest["entries"]:
                relative = full_backup._safe_relative(entry["path"])
                target = destination / Path(*PurePosixPath(relative).parts)
                resolved = target.resolve()
                if destination.resolve() not in resolved.parents:
                    raise full_backup.FullBackupError(
                        "Tentative de sortie de la restauration."
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
                with archive.open(f"payload/{relative}") as reader, temporary.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
                os.replace(temporary, target)
        return {
            "success": True,
            "files": manifest["files"],
            "payload_bytes": manifest["total_bytes"],
            "integrity_verified": True,
            "destination": str(destination),
            "manifest": manifest,
        }
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def create(
    destination: Path,
    *,
    passphrase: str,
    event_logger: EventLogger = _default_event_logger,
) -> dict[str, Any]:
    """Crée et vérifie un export explicite sans journaliser sa phrase secrète."""
    with _LOCK:
        target = _validate_destination(destination)
        plain = target.parent / f".portable.{uuid.uuid4().hex}.zip"
        encrypted = target.parent / f".{target.name}.{uuid.uuid4().hex}.partial"
        verify_plain = target.parent / f".portable-verify.{uuid.uuid4().hex}.zip"
        try:
            manifest = full_backup._build_plain_archive(
                plain,
                excluded_root_files=MACHINE_BOUND_SECRET_FILES,
                manifest_metadata={
                    "portable": True,
                    "dpapi_secrets_included": False,
                    "reauthentication_required": True,
                    "excluded_machine_bound": sorted(MACHINE_BOUND_SECRET_FILES),
                },
            )
            full_backup._validate_plain_archive(plain)
            encrypt_file(plain, encrypted, passphrase=passphrase)
            decrypt_file(encrypted, verify_plain, passphrase=passphrase)
            verified = full_backup._validate_plain_archive(verify_plain)
            if verified.get("entries") != manifest.get("entries"):
                raise PortableBackupError("La vérification portable diffère de la capture.")
            os.replace(encrypted, target)
            result = {
                "success": True,
                "filename": target.name,
                "size_bytes": target.stat().st_size,
                "files": manifest["files"],
                "payload_bytes": manifest["total_bytes"],
                "encrypted": True,
                "integrity_verified": True,
                "portable": True,
                "dpapi_secrets_included": False,
                "reauthentication_required": True,
            }
            event_logger("portable_backup_create", result)
            return result
        except Exception as exc:
            event_logger(
                "portable_backup_create",
                {"success": False, "error_code": type(exc).__name__},
            )
            raise
        finally:
            plain.unlink(missing_ok=True)
            encrypted.unlink(missing_ok=True)
            verify_plain.unlink(missing_ok=True)


def restore_to(source: Path, destination: Path, *, passphrase: str) -> dict[str, Any]:
    """Restaure vers une zone isolée ; aucune donnée active n'est remplacée."""
    with _LOCK:
        if (
            source.suffix.lower() != PORTABLE_EXTENSION
            or not source.is_file()
            or source.is_symlink()
        ):
            raise PortableBackupError("Le bundle portable source est invalide.")
        if not 1 <= source.stat().st_size <= MAX_ENCRYPTED_BYTES:
            raise PortableBackupError("La taille du bundle portable est invalide.")
        plain = destination.parent / f".portable-restore.{uuid.uuid4().hex}.zip"
        try:
            decrypt_file(source, plain, passphrase=passphrase)
            manifest = full_backup._validate_plain_archive(plain)
            if (
                manifest.get("portable") is not True
                or manifest.get("dpapi_secrets_included") is not False
                or manifest.get("reauthentication_required") is not True
                or any(
                    entry.get("path") in MACHINE_BOUND_SECRET_FILES
                    for entry in manifest.get("entries", [])
                )
            ):
                raise PortableBackupError("Le contrat du bundle portable est invalide.")
            result = _extract(plain, destination)
            result.update({
                "portable": True,
                "dpapi_secrets_included": False,
                "reauthentication_required": True,
            })
            return result
        finally:
            plain.unlink(missing_ok=True)


def verify(
    source: Path,
    *,
    passphrase: str,
    event_logger: EventLogger = _default_event_logger,
) -> dict[str, Any]:
    try:
        with tempfile.TemporaryDirectory(prefix="marvin-portable-verify-") as directory:
            result = restore_to(source, Path(directory) / "restored", passphrase=passphrase)
        verified = {
            **result,
            "destination": None,
            "manifest": None,
            "verified_only": True,
        }
        event_logger("portable_backup_verify", verified)
        return verified
    except Exception as exc:
        event_logger(
            "portable_backup_verify",
            {"success": False, "error_code": type(exc).__name__},
        )
        raise
