"""Réplication vérifiée d'un bundle global déjà chiffré."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR


KEEP_LAST = 3
BUNDLE_PATTERN = re.compile(
    r"^marvin_full_\d{8}_\d{6}_\d{6}\.mrvfull$"
)
EventLogger = Callable[[str, dict[str, Any]], None]


class BackupReplicationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_event_logger(event: str, attributes: dict[str, Any]) -> None:
    try:
        import audit

        audit.log_action(
            event,
            result={
                "success": bool(attributes.get("success")),
                "idempotent": bool(attributes.get("idempotent")),
                "size_bytes": int(attributes.get("size_bytes") or 0),
                "error": attributes.get("error_code"),
            },
            source="offline_backup_replication",
        )
    except Exception:
        pass


def _validate_destination(root: Path) -> Path:
    raw = root.absolute()
    if raw.is_symlink() or not raw.is_dir():
        raise BackupReplicationError(
            "La destination doit être un répertoire existant sans lien symbolique."
        )
    resolved = raw.resolve()
    data = Path(DATA_DIR).resolve()
    if resolved == data or data in resolved.parents or resolved in data.parents:
        raise BackupReplicationError(
            "La réplication doit cibler un stockage distinct du répertoire data."
        )
    return resolved


def _write_sidecar(destination: Path, target: Path, size: int, digest: str) -> None:
    sidecar = destination / f"{target.name}.sha256.json"
    temporary = destination / f".{sidecar.name}.{uuid.uuid4().hex}.partial"
    try:
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "filename": target.name,
                    "size_bytes": size,
                    "sha256": digest,
                    "replicated_at": datetime.now(timezone.utc).isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temporary, sidecar)
    finally:
        temporary.unlink(missing_ok=True)


def replicate(
    source: Path,
    destination_root: Path,
    *,
    event_logger: EventLogger = _default_event_logger,
) -> dict[str, Any]:
    if not BUNDLE_PATTERN.fullmatch(source.name) or not source.is_file():
        raise BackupReplicationError("Le bundle source est invalide.")
    root = _validate_destination(destination_root)
    destination = root / "MarvinBackups"
    destination.mkdir(exist_ok=True)
    if destination.is_symlink():
        raise BackupReplicationError("Le répertoire MarvinBackups ne peut pas être un lien.")
    target = destination / source.name
    digest = _sha256(source)
    size = source.stat().st_size
    same_volume = source.stat().st_dev == root.stat().st_dev
    try:
        if target.exists():
            if target.is_symlink() or target.stat().st_size != size or _sha256(target) != digest:
                raise BackupReplicationError(
                    "Un bundle homonyme différent existe sur la destination."
                )
            result = {
                "success": True,
                "filename": target.name,
                "size_bytes": size,
                "sha256": digest,
                "integrity_verified": True,
                "idempotent": True,
                "same_volume": same_volume,
                "destination": str(destination),
            }
            _write_sidecar(destination, target, size, digest)
            event_logger("full_backup_replicate", result)
            return result
        temporary = destination / f".{target.name}.{uuid.uuid4().hex}.partial"
        try:
            with source.open("rb") as reader, temporary.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            if temporary.stat().st_size != size or _sha256(temporary) != digest:
                raise BackupReplicationError("La copie distante échoue au contrôle SHA-256.")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        if target.stat().st_size != size or _sha256(target) != digest:
            target.unlink(missing_ok=True)
            raise BackupReplicationError(
                "Le bundle publié échoue au contrôle SHA-256 final."
            )
        _write_sidecar(destination, target, size, digest)
        copies = sorted(
            destination.glob("marvin_full_*.mrvfull"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
            reverse=True,
        )
        rotation_deleted = 0
        for old in copies[KEEP_LAST:]:
            old.unlink()
            old.with_name(f"{old.name}.sha256.json").unlink(missing_ok=True)
            rotation_deleted += 1
        result = {
            "success": True,
            "filename": target.name,
            "size_bytes": size,
            "sha256": digest,
            "integrity_verified": True,
            "idempotent": False,
            "same_volume": same_volume,
            "rotation_deleted": rotation_deleted,
            "destination": str(destination),
        }
        event_logger("full_backup_replicate", result)
        return result
    except Exception as exc:
        event_logger(
            "full_backup_replicate",
            {"success": False, "error_code": type(exc).__name__},
        )
        raise
