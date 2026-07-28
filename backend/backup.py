"""Sauvegarde et restauration cohérentes de la base SQLite de Marvin."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import DB_PATH, DATA_DIR
from backup_encryption import decrypt_file, encrypt_file


BACKUP_DIR = DATA_DIR / "backups"
KEEP_LAST = 14
_BACKUP_NAME = re.compile(
    r"^secretary_\d{8}_\d{6}(?:_\d{6})?(?:_\d+)?\.(?:db|mrvbak)$"
)
_CHECKSUM = re.compile(r"^[0-9a-f]{64}$")

Clock = Callable[[], datetime]
EventLogger = Callable[[str, dict[str, Any]], None]


def _default_event_logger(event: str, attributes: dict[str, Any]) -> None:
    """Réutilise le journal d'audit borné sans y placer chemin ni contenu."""
    try:
        import audit

        failed = attributes.get("success") is False
        audit.log_action(
            event,
            result={
                "success": not failed,
                "error": attributes.get("error_code") if failed else None,
            },
            source="runtime",
        )
    except Exception:
        pass


class BackupService:
    """Service injectable sérialisant sauvegardes et restaurations du process."""

    def __init__(
        self,
        database_path: str | Path = DB_PATH,
        backup_dir: str | Path = BACKUP_DIR,
        *,
        keep_last: int = KEEP_LAST,
        clock: Clock | None = None,
        event_logger: EventLogger = _default_event_logger,
    ) -> None:
        if isinstance(keep_last, bool) or not 2 <= int(keep_last) <= 365:
            raise ValueError("keep_last doit être compris entre 2 et 365.")
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir)
        self.keep_last = int(keep_last)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._event_logger = event_logger
        self._lock = threading.RLock()

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(path),
            timeout=30.0,
            check_same_thread=False,
        )
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA cell_size_check=ON")
        return connection

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _fsync(path: Path) -> None:
        with path.open("r+b") as stream:
            os.fsync(stream.fileno())

    def _integrity(self, path: Path, *, full: bool) -> int:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("La base SQLite est absente ou vide.")
        connection = self._connect(path)
        try:
            pragma = "integrity_check" if full else "quick_check"
            rows = connection.execute(f"PRAGMA {pragma}").fetchall()
            if rows != [("ok",)]:
                raise ValueError(f"Le contrôle SQLite {pragma} a échoué.")
            foreign_key_violations = len(
                connection.execute("PRAGMA foreign_key_check").fetchall()
            )
            return foreign_key_violations
        finally:
            connection.close()

    def _copy_database(self, source_path: Path, destination_path: Path) -> None:
        source = self._connect(source_path)
        destination = self._connect(destination_path)
        try:
            source.execute("PRAGMA query_only=ON")
            source.backup(destination, pages=256, sleep=0.05)
            destination.commit()
        finally:
            destination.close()
            source.close()

    def _next_destination(self) -> Path:
        stamp = self._clock().astimezone(timezone.utc).strftime(
            "%Y%m%d_%H%M%S_%f"
        )
        candidate = self.backup_dir / f"secretary_{stamp}.mrvbak"
        suffix = 1
        while candidate.exists():
            candidate = self.backup_dir / f"secretary_{stamp}_{suffix}.mrvbak"
            suffix += 1
        return candidate

    @staticmethod
    def _checksum_path(path: Path) -> Path:
        return path.with_suffix(path.suffix + ".sha256")

    def _write_checksum(self, database_path: Path, digest: str) -> None:
        final = self._checksum_path(database_path)
        temporary = final.with_name(f".{final.name}.{uuid.uuid4().hex}.partial")
        try:
            temporary.write_text(
                f"{digest}  {database_path.name}\n",
                encoding="ascii",
            )
            self._fsync(temporary)
            os.replace(temporary, final)
        finally:
            temporary.unlink(missing_ok=True)

    def _verify_checksum(self, path: Path) -> bool:
        sidecar = self._checksum_path(path)
        if not sidecar.is_file():
            return False
        raw = sidecar.read_text(encoding="ascii").strip().split()
        if len(raw) != 2 or raw[1] != path.name or not _CHECKSUM.fullmatch(
            raw[0]
        ):
            raise ValueError("Le manifeste SHA-256 est invalide.")
        if not hmac.compare_digest(raw[0], self._sha256(path)):
            raise ValueError("L'empreinte SHA-256 de la sauvegarde est invalide.")
        return True

    def _prune_locked(self) -> tuple[int, int]:
        backups = sorted(
            list(self.backup_dir.glob("secretary_*.db"))
            + list(self.backup_dir.glob("secretary_*.mrvbak")),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        deleted = 0
        errors = 0
        for old in backups[self.keep_last :]:
            try:
                old.unlink()
                self._checksum_path(old).unlink(missing_ok=True)
                deleted += 1
            except OSError:
                errors += 1
        return deleted, errors

    def _create_locked(self, *, prune: bool) -> dict[str, Any]:
        if not self.database_path.is_file():
            raise FileNotFoundError("La base SQLite source est absente.")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._integrity(self.database_path, full=False)
        destination = self._next_destination()
        snapshot = self.backup_dir / f".snapshot.{uuid.uuid4().hex}.db"
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
        try:
            self._copy_database(self.database_path, snapshot)
            foreign_key_violations = self._integrity(
                snapshot,
                full=False,
            )
            self._fsync(snapshot)
            encryption = encrypt_file(snapshot, temporary)
            verified = self.backup_dir / f".verify.{uuid.uuid4().hex}.db"
            try:
                decrypted = decrypt_file(temporary, verified)
                self._integrity(verified, full=False)
                if decrypted != encryption:
                    raise ValueError("La vérification chiffrée a échoué.")
            finally:
                verified.unlink(missing_ok=True)
            os.replace(temporary, destination)
            digest = str(encryption["sha256"])
        except BaseException:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            self._checksum_path(destination).unlink(missing_ok=True)
            raise
        finally:
            snapshot.unlink(missing_ok=True)
        deleted, rotation_errors = self._prune_locked() if prune else (0, 0)
        return {
            "success": True,
            "filename": destination.name,
            "path": str(destination),
            "size_kb": round(destination.stat().st_size / 1024, 1),
            "sha256": digest,
            "encrypted": True,
            "portable": False,
            "integrity_verified": True,
            "foreign_key_violations": foreign_key_violations,
            "rotation_deleted": deleted,
            "rotation_warnings": rotation_errors,
        }

    def create(self) -> dict[str, Any]:
        with self._lock:
            try:
                result = self._create_locked(prune=True)
                self._event_logger(
                    "database_backup",
                    {
                        "success": True,
                        "size_kb": result["size_kb"],
                        "rotation_warnings": result["rotation_warnings"],
                        "foreign_key_violations": result[
                            "foreign_key_violations"
                        ],
                    },
                )
                return result
            except Exception as exc:
                result = {
                    "success": False,
                    "error": "La sauvegarde SQLite a échoué.",
                    "error_code": type(exc).__name__,
                }
                self._event_logger("database_backup", result)
                return result

    def _resolve_backup(self, filename: str) -> Path:
        if not isinstance(filename, str) or not _BACKUP_NAME.fullmatch(
            filename
        ):
            raise ValueError("Nom de fichier de sauvegarde invalide.")
        candidate = self.backup_dir / filename
        if candidate.resolve().parent != self.backup_dir.resolve():
            raise ValueError("Nom de fichier de sauvegarde invalide.")
        if not candidate.is_file():
            raise FileNotFoundError("La sauvegarde demandée est introuvable.")
        return candidate

    def _restore_from(self, source: Path) -> int:
        self._copy_database(source, self.database_path)
        return self._integrity(self.database_path, full=True)

    @contextmanager
    def _materialize(self, source: Path):
        if source.suffix == ".db":
            yield source
            return
        temporary = self.backup_dir / f".restore.{uuid.uuid4().hex}.db"
        try:
            decrypt_file(source, temporary)
            yield temporary
        finally:
            temporary.unlink(missing_ok=True)

    def restore(self, filename: str) -> dict[str, Any]:
        with self._lock:
            pre_restore: dict[str, Any] | None = None
            phase = "resolve"
            try:
                source = self._resolve_backup(filename)
                phase = "validate"
                with self._materialize(source) as materialized:
                    foreign_key_violations = self._integrity(materialized, full=True)
                    checksum_verified = (
                        True if source.suffix == ".mrvbak"
                        else self._verify_checksum(source)
                    )
                    pre_restore = self._create_locked(prune=False)
                    phase = "restore"
                    restored_foreign_key_violations = self._restore_from(materialized)
                if (
                    restored_foreign_key_violations
                    != foreign_key_violations
                ):
                    raise RuntimeError(
                        "La restauration a modifié les violations relationnelles."
                    )
                deleted, rotation_errors = self._prune_locked()
                result = {
                    "success": True,
                    "restored_from": filename,
                    "pre_restore_backup": pre_restore["path"],
                    "pre_restore_filename": pre_restore["filename"],
                    "checksum_verified": checksum_verified,
                    "integrity_verified": True,
                    "foreign_key_violations": foreign_key_violations,
                    "compensated": False,
                    "rotation_deleted": deleted,
                    "rotation_warnings": rotation_errors,
                }
                self._event_logger(
                    "database_restore",
                    {
                        "success": True,
                        "checksum_verified": checksum_verified,
                        "rotation_warnings": rotation_errors,
                    },
                )
                return result
            except Exception as exc:
                compensated = False
                compensation_error: str | None = None
                if pre_restore and pre_restore.get("path"):
                    try:
                        with self._materialize(Path(pre_restore["path"])) as rollback:
                            self._restore_from(rollback)
                        compensated = True
                    except Exception as rollback_exc:
                        compensation_error = type(rollback_exc).__name__
                error_code = (
                    "backup_not_found"
                    if isinstance(exc, FileNotFoundError)
                    else (
                        "invalid_backup"
                        if phase in {"resolve", "validate"}
                        else "restore_failed"
                    )
                )
                result = {
                    "success": False,
                    "error": (
                        "La sauvegarde demandée est introuvable."
                        if error_code == "backup_not_found"
                        else (
                            "La sauvegarde est invalide ou corrompue."
                            if error_code == "invalid_backup"
                            else "La restauration SQLite a échoué."
                        )
                    ),
                    "error_code": error_code,
                    "exception_type": type(exc).__name__,
                    "compensated": compensated,
                }
                if compensation_error:
                    result["compensation_error_type"] = compensation_error
                self._event_logger(
                    "database_restore",
                    {
                        "success": False,
                        "error_code": error_code,
                        "compensated": compensated,
                        "compensation_failed": bool(compensation_error),
                    },
                )
                return result

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.backup_dir.is_dir():
                return []
            backups = sorted(
                list(self.backup_dir.glob("secretary_*.db"))
                + list(self.backup_dir.glob("secretary_*.mrvbak")),
                key=lambda path: (path.stat().st_mtime_ns, path.name),
                reverse=True,
            )[:365]
            return [
                {
                    "filename": path.name,
                    "path": str(path),
                    "size_kb": round(path.stat().st_size / 1024, 1),
                    "created_at": datetime.fromtimestamp(
                        path.stat().st_mtime,
                        tz=timezone.utc,
                    ).isoformat(),
                    "checksum_available": self._checksum_path(path).is_file(),
                    "encrypted": path.suffix == ".mrvbak",
                    "portable": False if path.suffix == ".mrvbak" else None,
                }
                for path in backups
            ]


service = BackupService()
create_backup = service.create
restore_backup = service.restore
list_backups = service.list
