"""Maintenance SQLite hors ligne, vérifiée et compensable."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from backup import BackupService
from config import DATA_DIR, DB_PATH


MIN_FREE_RESERVE = 512 * 1024 * 1024
REPORT_RETENTION_DAYS = 365
MAX_REPORTS = 32
RuntimeProbe = Callable[[], bool]
_LOCK = threading.RLock()


class SqliteMaintenanceError(RuntimeError):
    pass


@contextmanager
def _maintenance_lock(database_path: Path):
    lock_path = database_path.with_suffix(database_path.suffix + ".maintenance.lock")
    with _LOCK:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SqliteMaintenanceError(
                    "Une autre maintenance SQLite est déjà active."
                ) from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def runtime_is_active() -> bool:
    for port in (3000, 8005):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(0.25)
            if client.connect_ex(("127.0.0.1", port)) == 0:
                return True
    return False


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA secure_delete=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA cell_size_check=ON")
    return connection


def _validate(connection: sqlite3.Connection) -> dict[str, int]:
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)]:
        raise SqliteMaintenanceError("PRAGMA integrity_check a échoué.")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise SqliteMaintenanceError("Des violations de clés étrangères sont présentes.")
    return {
        "page_count": int(connection.execute("PRAGMA page_count").fetchone()[0]),
        "freelist_count": int(connection.execute("PRAGMA freelist_count").fetchone()[0]),
    }


def _checkpoint(connection: sqlite3.Connection) -> dict[str, int]:
    busy, log_pages, checkpointed = connection.execute(
        "PRAGMA wal_checkpoint(TRUNCATE)"
    ).fetchone()
    if int(busy) != 0:
        raise SqliteMaintenanceError("Le checkpoint WAL est occupé; maintenance annulée.")
    return {
        "busy": int(busy),
        "log_pages": int(log_pages),
        "checkpointed_pages": int(checkpointed),
    }


class SqliteMaintenance:
    def __init__(
        self,
        database_path: str | Path = DB_PATH,
        backup_dir: str | Path | None = None,
        report_dir: str | Path | None = None,
        *,
        runtime_probe: RuntimeProbe = runtime_is_active,
    ) -> None:
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir or (Path(DATA_DIR) / "backups"))
        self.report_dir = Path(report_dir or (Path(DATA_DIR) / "maintenance"))
        self.runtime_probe = runtime_probe
        self.backups = BackupService(
            self.database_path,
            self.backup_dir,
            event_logger=lambda _event, _attributes: None,
        )

    def _offline_preflight(self) -> None:
        if self.runtime_probe():
            raise SqliteMaintenanceError(
                "Marvin doit être arrêté avant toute maintenance SQLite."
            )
        if not self.database_path.is_file() or self.database_path.stat().st_size == 0:
            raise SqliteMaintenanceError("La base SQLite est absente ou vide.")
        required = self.database_path.stat().st_size * 3 + MIN_FREE_RESERVE
        free = shutil.disk_usage(self.database_path.parent).free
        if free < required:
            raise SqliteMaintenanceError(
                "Espace disque insuffisant pour sauvegarde, VACUUM et rollback."
            )

    def _write_report(self, payload: dict[str, Any]) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        cutoff = datetime.now(UTC) - timedelta(days=REPORT_RETENTION_DAYS)
        reports = sorted(
            (
                path
                for path in self.report_dir.glob("sqlite-maintenance-*.json")
                if path.name != "sqlite-maintenance-latest.json"
            ),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        deleted = 0
        warnings = 0
        for index, old in enumerate(reports):
            expired = datetime.fromtimestamp(old.stat().st_mtime, UTC) < cutoff
            over_limit = index >= MAX_REPORTS
            if not expired and not over_limit:
                continue
            try:
                old.unlink()
                deleted += 1
            except OSError:
                warnings += 1
        payload["report_retention"] = {
            "days": REPORT_RETENTION_DAYS,
            "maximum": MAX_REPORTS,
            "deleted": deleted,
            "warnings": warnings,
        }
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self.report_dir / f"sqlite-maintenance-{stamp}.json"
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            latest = self.report_dir / "sqlite-maintenance-latest.json"
            latest_temporary = latest.with_name(f".{latest.name}.{uuid.uuid4().hex}.tmp")
            try:
                latest_temporary.write_text(encoded, encoding="utf-8", newline="\n")
                os.replace(latest_temporary, latest)
            finally:
                latest_temporary.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def run(self) -> dict[str, Any]:
        with _maintenance_lock(self.database_path):
            return self._run_locked()

    def _run_locked(self) -> dict[str, Any]:
        started = time.perf_counter()
        backup_filename: str | None = None
        phase = "preflight"
        before_bytes = 0
        before: dict[str, int] = {}
        after: dict[str, int] = {}
        checkpoint_before: dict[str, int] = {}
        checkpoint_after: dict[str, int] = {}
        try:
            self._offline_preflight()
            before_bytes = self.database_path.stat().st_size
            phase = "backup"
            backup = self.backups.create()
            if not backup.get("success") or not backup.get("integrity_verified"):
                raise SqliteMaintenanceError("La sauvegarde préalable vérifiée a échoué.")
            backup_filename = str(backup["filename"])
            phase = "checkpoint_before"
            connection = _connect(self.database_path)
            try:
                checkpoint_before = _checkpoint(connection)
                phase = "integrity_before"
                before = _validate(connection)
                phase = "vacuum"
                connection.execute("VACUUM")
                phase = "checkpoint_after"
                checkpoint_after = _checkpoint(connection)
                phase = "integrity_after"
                after = _validate(connection)
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode").fetchone()[0]
                ).casefold()
                if journal_mode != "wal":
                    raise SqliteMaintenanceError("Le mode WAL n'a pas été conservé.")
            finally:
                connection.close()
            wal_path = Path(str(self.database_path) + "-wal")
            if wal_path.exists() and wal_path.stat().st_size != 0:
                raise SqliteMaintenanceError("Le WAL n'est pas vide après checkpoint.")
            payload = {
                "schema_version": 1,
                "success": True,
                "generated_at": datetime.now(UTC).isoformat(),
                "backup_filename": backup_filename,
                "before_bytes": before_bytes,
                "after_bytes": self.database_path.stat().st_size,
                "before": before,
                "after": after,
                "checkpoint_before": checkpoint_before,
                "checkpoint_after": checkpoint_after,
                "integrity": "ok",
                "foreign_keys": "ok",
                "compensated": False,
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
            payload["report_path"] = str(self._write_report(payload))
            return payload
        except Exception as exc:
            compensation: dict[str, Any] | None = None
            if backup_filename:
                compensation = self.backups.restore(backup_filename)
            payload = {
                "schema_version": 1,
                "success": False,
                "generated_at": datetime.now(UTC).isoformat(),
                "phase": phase,
                "error_type": type(exc).__name__,
                "error": str(exc)[:240],
                "backup_filename": backup_filename,
                "compensated": bool(compensation and compensation.get("success")),
                "compensation_error": (
                    None if not compensation else compensation.get("error_code")
                ),
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
            try:
                payload["report_path"] = str(self._write_report(payload))
            except OSError:
                payload["report_path"] = None
            return payload

    def rollback(self, backup_filename: str) -> dict[str, Any]:
        with _maintenance_lock(self.database_path):
            return self._rollback_locked(backup_filename)

    def _rollback_locked(self, backup_filename: str) -> dict[str, Any]:
        self._offline_preflight()
        result = self.backups.restore(backup_filename)
        if not result.get("success"):
            return result
        connection = _connect(self.database_path)
        try:
            _checkpoint(connection)
            _validate(connection)
        finally:
            connection.close()
        return {**result, "offline_verified": True}


service = SqliteMaintenance()
