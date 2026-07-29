"""Application hors ligne compensée d'un bundle global Marvin."""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import full_backup
from config import DATA_DIR


Reconcile = Callable[[], dict[str, Any]]
CreateBackup = Callable[[], dict[str, Any]]
EventLogger = Callable[[str, dict[str, Any]], None]


class FullRecoveryError(RuntimeError):
    pass


def _default_event_logger(event: str, attributes: dict[str, Any]) -> None:
    try:
        import audit

        audit.log_action(
            event,
            result={
                "success": bool(attributes.get("success")),
                "compensated": bool(attributes.get("compensated")),
                "files": int(attributes.get("files") or 0),
                "error": attributes.get("error_code"),
            },
            source="offline_recovery",
        )
    except Exception:
        pass


def _default_reconcile() -> dict[str, Any]:
    from database_bootstrap import initialize_database
    import memory_lifecycle
    import vector_store

    try:
        initialize_database()
        return asyncio.run(memory_lifecycle.repair_consistency(dry_run=False))
    finally:
        vector_store.close_client()


def _validate_database(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise FullRecoveryError("La base restaurée échoue au contrôle d'intégrité.")
    finally:
        connection.close()


def _managed_names() -> set[str]:
    return {
        "secretary.db",
        *full_backup.AUTHORITATIVE_ROOT_FILES,
        *full_backup.AUTHORITATIVE_DIRECTORIES,
    }


def _move_managed(source: Path, destination: Path) -> int:
    moved = 0
    destination.mkdir(parents=True, exist_ok=False)
    for name in sorted(_managed_names()):
        current = source / name
        if not current.exists():
            continue
        if current.is_symlink():
            raise FullRecoveryError("Un lien symbolique interdit bloque la restauration.")
        os.replace(current, destination / name)
        moved += 1
    return moved


def _remove_managed(root: Path) -> None:
    for name in sorted(_managed_names()):
        path = root / name
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)


def _restore_rollback(rollback: Path, target: Path) -> None:
    _remove_managed(target)
    for item in sorted(rollback.iterdir(), key=lambda candidate: candidate.name):
        os.replace(item, target / item.name)


def apply_offline(
    source: Path,
    *,
    target_data: Path = Path(DATA_DIR),
    reconcile: Reconcile = _default_reconcile,
    create_backup: CreateBackup = full_backup.create,
    event_logger: EventLogger = _default_event_logger,
) -> dict[str, Any]:
    """Remplace les seules autorités sauvegardées et compense tout échec."""
    raw_target = target_data.absolute()
    if raw_target.is_symlink():
        raise FullRecoveryError("Le répertoire data cible ne peut pas être un lien.")
    target = raw_target.resolve()
    if not target.is_dir():
        raise FullRecoveryError("Le répertoire data cible doit exister sans être un lien.")
    parent = target.parent
    operation_id = uuid.uuid4().hex
    stage = parent / f".marvin-restore-stage-{operation_id}"
    rollback = parent / f".marvin-restore-rollback-{operation_id}"
    succeeded = False
    compensated = False
    safety_filename = ""
    try:
        restored = full_backup.restore_to(source, stage)
        _validate_database(stage / "secretary.db")
        safety = create_backup()
        if not safety.get("success") or not safety.get("filename"):
            raise FullRecoveryError("Le point de retour préalable n'a pas été créé.")
        safety_filename = str(safety["filename"])
        try:
            _move_managed(target, rollback)
            for item in sorted(stage.iterdir(), key=lambda candidate: candidate.name):
                os.replace(item, target / item.name)
            reconciliation = reconcile()
            if not reconciliation.get("success"):
                raise FullRecoveryError("La reconstruction des projections a échoué.")
        except BaseException:
            _restore_rollback(rollback, target)
            compensation = reconcile()
            if not compensation.get("success"):
                raise FullRecoveryError(
                    "La restauration a échoué et ses projections n'ont pas pu être compensées."
                )
            compensated = True
            raise
        result = {
            "success": True,
            "files": restored["files"],
            "payload_bytes": restored["payload_bytes"],
            "integrity_verified": True,
            "memory_reconciled": True,
            "pre_restore_filename": safety_filename,
            "compensated": False,
        }
        succeeded = True
        event_logger("full_backup_apply", result)
        return result
    except BaseException as exc:
        event_logger(
            "full_backup_apply",
            {
                "success": False,
                "compensated": compensated,
                "error_code": type(exc).__name__,
            },
        )
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if succeeded or compensated or (rollback.exists() and not any(rollback.iterdir())):
            shutil.rmtree(rollback, ignore_errors=True)
