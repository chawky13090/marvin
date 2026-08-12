"""Bundle chiffré des données autoritatives et artefacts utilisateur Marvin."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from collections.abc import Callable

from app_version import APP_VERSION
from backup_encryption import decrypt_file, encrypt_file
from config import DATA_DIR, DB_PATH


SCHEMA_VERSION = 1
PURPOSE = "marvin-full-backup-v1"
BACKUP_DIR = Path(DATA_DIR) / "backups"
MAX_FILES = 20_000
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024

AUTHORITATIVE_ROOT_FILES = frozenset({
    "coding_jobs.json",
    "coding_jobs.json.bak",
    "cortex_recipes.json",
    "forge_runs.jsonl",
    "forge_scenarios.json",
    "frontier_arena_matches.jsonl",
    "frontier_arena_submissions.jsonl",
    "frontier_arena_votes.jsonl",
    "mission_events.jsonl",
    "model_market_observations.jsonl",
    "research_swarm_runs.jsonl",
    "research_swarm_jobs.json",
    "skills_learning_log.json",
    "skills_stats.json",
    "truth_ledger.jsonl",
    "windows_secrets.dpapi.json",
    "windows_secrets.metadata.json",
})
AUTHORITATIVE_DIRECTORIES = frozenset({
    "chat_uploads",
    "code_outputs",
    "coding_missions",
    "coding_workspaces",
    "documents",
    "documents_generes",
    "generated_docs",
    "engineering_radar",
    "logos",
    "rollback",
    "maintenance",
    "screenshots",
    "skills",
    "site_crawls",
    "webapps",
})
REBUILDABLE_OR_TRANSIENT = frozenset({
    "backups",
    "cache",
    "hyperv-store-backup",
    "logs",
    "qdrant",
    "reranker_cache",
    "validation",
    "vm_lab_jobs",
    "web_media",
})
REBUILDABLE_ROOT_FILES = frozenset({
    "marvin.db",
    "model_catalog_watch.json",
})
MACHINE_LOCAL_DIRECTORIES = frozenset({
    "install",
})
MACHINE_LOCAL_ROOT_FILES = frozenset({
    "debian-vm-install-result.json",
    "elevated_token.json",
    "hyperv-access-result.json",
    "hyperv-legacy-removal-result.json",
    "hyperv-orphan-cleanup-result.json",
    "hyperv-store-audit.json",
    "hyperv_test_forge.json",
    "install-capabilities.json",
    "libreoffice-capability.json",
    "linux_test_forge_session.json",
    "memory_mesh.json",
    "vm_lab_install_job.json",
    "vm_lab_iso_verification.json",
    "windows-vm-install-result.json",
    "windows-vm-provision-result.json",
})
AUTHORITATIVE_DIRECTORY_PATTERNS = (
    re.compile(r"^skills_backup_\d{8}-\d{6}$"),
)
AUTHORITATIVE_ROOT_FILE_PATTERNS = (
    re.compile(r'^[^\\/:*?"<>|]{1,200}\.(?:pdf|docx|xlsx|pptx|md|txt)$', re.IGNORECASE),
)
_LOCK = threading.RLock()
KEEP_LAST = 3


class FullBackupError(RuntimeError):
    pass


EventLogger = Callable[[str, dict[str, Any]], None]


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
            source="runtime",
        )
    except Exception:
        pass


def _safe_relative(value: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if (
        not path.parts
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise FullBackupError("Chemin de bundle invalide.")
    return path.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_sqlite(destination: Path) -> None:
    source = sqlite3.connect(str(DB_PATH), timeout=30.0)
    target = sqlite3.connect(str(destination), timeout=30.0)
    try:
        source.execute("PRAGMA query_only=ON")
        source.backup(target, pages=256, sleep=0.05)
        target.commit()
        rows = target.execute("PRAGMA integrity_check").fetchall()
        if rows != [("ok",)]:
            raise FullBackupError("Le snapshot SQLite global est invalide.")
    finally:
        target.close()
        source.close()


def _inventory(
    *,
    excluded_root_files: frozenset[str] = frozenset(),
) -> list[tuple[str, Path]]:
    data_dir = Path(DATA_DIR)
    patterned_directories = {
        item.name
        for item in data_dir.iterdir()
        if item.is_dir()
        and any(pattern.fullmatch(item.name) for pattern in AUTHORITATIVE_DIRECTORY_PATTERNS)
    }
    patterned_root_files = {
        item.name
        for item in data_dir.iterdir()
        if item.is_file()
        and any(pattern.fullmatch(item.name) for pattern in AUTHORITATIVE_ROOT_FILE_PATTERNS)
    }
    unknown_directories = {
        item.name
        for item in data_dir.iterdir()
        if item.is_dir()
        and item.name not in AUTHORITATIVE_DIRECTORIES
        and item.name not in REBUILDABLE_OR_TRANSIENT
        and item.name not in MACHINE_LOCAL_DIRECTORIES
        and item.name not in patterned_directories
    }
    unknown_files = {
        item.name
        for item in data_dir.iterdir()
        if item.is_file()
        and item.name != Path(DB_PATH).name
        and item.name not in AUTHORITATIVE_ROOT_FILES
        and item.name not in MACHINE_LOCAL_ROOT_FILES
        and item.name not in REBUILDABLE_ROOT_FILES
        and item.name not in patterned_root_files
        and not item.name.endswith((".lock", ".tmp", ".partial"))
        and not item.name.startswith(("audit.", "bug_log.", "skills_match_log."))
        and item.name not in {"audit.jsonl", "bug_log.jsonl", "skills_match_log.jsonl"}
    }
    if unknown_directories or unknown_files:
        raise FullBackupError(
            "Persistance non classifiée : "
            + ", ".join(sorted(unknown_directories | unknown_files))
        )
    selected: list[tuple[str, Path]] = []
    for name in sorted(AUTHORITATIVE_ROOT_FILES):
        if name in excluded_root_files:
            continue
        source = data_dir / name
        if source.is_file():
            selected.append((name, source))
    for name in sorted(patterned_root_files):
        selected.append((name, data_dir / name))
    for directory in sorted(AUTHORITATIVE_DIRECTORIES | patterned_directories):
        root = data_dir / directory
        if not root.exists():
            continue
        for source in sorted(root.rglob("*")):
            if source.is_symlink():
                raise FullBackupError("Les liens symboliques sont interdits dans un bundle.")
            if source.is_file() and not source.name.endswith((".lock", ".tmp", ".partial")):
                selected.append((source.relative_to(data_dir).as_posix(), source))
    if len(selected) + 1 > MAX_FILES:
        raise FullBackupError("Le bundle dépasse le nombre maximal de fichiers.")
    return selected


def _copy_bounded(source: Path, destination: Path) -> int:
    size = source.stat().st_size
    if size > MAX_FILE_BYTES:
        raise FullBackupError("Un fichier dépasse la taille maximale du bundle.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if destination.stat().st_size != size:
        raise FullBackupError("Un fichier a changé pendant sa capture.")
    return size


def _build_plain_archive(
    destination: Path,
    *,
    excluded_root_files: frozenset[str] = frozenset(),
    manifest_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reserved_manifest_keys = {
        "schema_version",
        "created_at",
        "marvin_version",
        "files",
        "total_bytes",
        "entries",
        "excluded_rebuildable",
    }
    if manifest_metadata and reserved_manifest_keys.intersection(manifest_metadata):
        raise FullBackupError("Une métadonnée tente d'écraser le manifeste du bundle.")
    with tempfile.TemporaryDirectory(prefix="marvin-full-stage-") as directory:
        stage = Path(directory)
        payload = stage / "payload"
        sqlite_path = payload / "secretary.db"
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        _snapshot_sqlite(sqlite_path)
        entries: list[dict[str, Any]] = []
        total = 0
        sources = [
            ("secretary.db", sqlite_path),
            *_inventory(excluded_root_files=excluded_root_files),
        ]
        for relative, source in sources:
            safe = _safe_relative(relative)
            staged = payload / Path(*PurePosixPath(safe).parts)
            if source != staged:
                total += _copy_bounded(source, staged)
            else:
                total += staged.stat().st_size
            if total > MAX_TOTAL_BYTES:
                raise FullBackupError("Le bundle dépasse la taille totale maximale.")
            entries.append({
                "path": safe,
                "size": staged.stat().st_size,
                "sha256": _sha256(staged),
            })
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "marvin_version": APP_VERSION,
            "files": len(entries),
            "total_bytes": total,
            "entries": entries,
            "excluded_rebuildable": sorted(REBUILDABLE_OR_TRANSIENT),
        }
        if manifest_metadata:
            manifest.update(manifest_metadata)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        with zipfile.ZipFile(
            destination,
            "x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            archive.write(stage / "manifest.json", "manifest.json")
            for entry in entries:
                archive.write(
                    payload / Path(*PurePosixPath(entry["path"]).parts),
                    f"payload/{entry['path']}",
                )
    return manifest


def _validate_plain_archive(archive_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 1:
            raise FullBackupError("Le bundle contient trop d'entrées.")
        names = [_safe_relative(info.filename) for info in infos]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise FullBackupError("Le catalogue du bundle est invalide.")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise FullBackupError("Le manifeste du bundle est illisible.") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != SCHEMA_VERSION
            or not isinstance(manifest.get("entries"), list)
            or len(manifest["entries"]) > MAX_FILES
        ):
            raise FullBackupError("Le manifeste du bundle est invalide.")
        expected = {
            _safe_relative(str(entry.get("path") or "")): entry
            for entry in manifest["entries"]
            if isinstance(entry, dict)
        }
        if len(expected) != len(manifest["entries"]):
            raise FullBackupError("Une entrée du manifeste est invalide.")
        declared_names = {"manifest.json"} | {
            f"payload/{relative}" for relative in expected
        }
        if set(names) != declared_names:
            raise FullBackupError(
                "Le bundle contient un fichier absent de son manifeste."
            )
        total = 0
        for relative, entry in expected.items():
            name = f"payload/{relative}"
            if name not in names:
                raise FullBackupError("Un fichier déclaré est absent du bundle.")
            info = archive.getinfo(name)
            size = int(entry.get("size", -1))
            digest = str(entry.get("sha256") or "")
            if (
                size < 0
                or size > MAX_FILE_BYTES
                or info.file_size != size
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise FullBackupError("Les métadonnées d'un fichier sont invalides.")
            hasher = hashlib.sha256()
            with archive.open(info) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
            if hasher.hexdigest() != digest:
                raise FullBackupError("L'intégrité d'un fichier du bundle a échoué.")
            total += size
            if total > MAX_TOTAL_BYTES:
                raise FullBackupError("Le bundle dépasse la taille totale maximale.")
        if total != manifest.get("total_bytes") or len(expected) != manifest.get("files"):
            raise FullBackupError("Les totaux du manifeste sont incohérents.")
        return manifest


def create(*, event_logger: EventLogger = _default_event_logger) -> dict[str, Any]:
    with _LOCK:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        destination = BACKUP_DIR / f"marvin_full_{stamp}.mrvfull"
        plain = BACKUP_DIR / f".full.{uuid.uuid4().hex}.zip"
        encrypted = BACKUP_DIR / f".{destination.name}.{uuid.uuid4().hex}.partial"
        verify = BACKUP_DIR / f".verify.{uuid.uuid4().hex}.zip"
        try:
            manifest = _build_plain_archive(plain)
            _validate_plain_archive(plain)
            encryption = encrypt_file(
                plain,
                encrypted,
                purpose=PURPOSE,
            )
            decrypt_file(encrypted, verify, purpose=PURPOSE)
            verified = _validate_plain_archive(verify)
            if verified["entries"] != manifest["entries"]:
                raise FullBackupError("La vérification du bundle diffère de la capture.")
            os.replace(encrypted, destination)
            existing = sorted(
                BACKUP_DIR.glob("marvin_full_*.mrvfull"),
                key=lambda item: (item.stat().st_mtime_ns, item.name),
                reverse=True,
            )
            rotation_deleted = 0
            for old in existing[KEEP_LAST:]:
                old.unlink()
                rotation_deleted += 1
            result = {
                "success": True,
                "filename": destination.name,
                "size_bytes": destination.stat().st_size,
                "files": manifest["files"],
                "payload_bytes": manifest["total_bytes"],
                "encrypted": True,
                "integrity_verified": True,
                "portable": False,
                "rotation_deleted": rotation_deleted,
            }
            event_logger("full_backup_create", result)
            return result
        except Exception as exc:
            event_logger("full_backup_create", {
                "success": False,
                "error_code": type(exc).__name__,
            })
            raise
        finally:
            plain.unlink(missing_ok=True)
            encrypted.unlink(missing_ok=True)
            verify.unlink(missing_ok=True)


def restore_to(source: Path, destination: Path) -> dict[str, Any]:
    """Restaure uniquement vers une zone vide et isolée pour validation."""
    with _LOCK:
        if destination.exists() and any(destination.iterdir()):
            raise FullBackupError("La destination de restauration doit être vide.")
        destination.mkdir(parents=True, exist_ok=True)
        plain = destination.parent / f".restore.{uuid.uuid4().hex}.zip"
        try:
            decrypt_file(source, plain, purpose=PURPOSE)
            manifest = _validate_plain_archive(plain)
            with zipfile.ZipFile(plain, "r") as archive:
                for entry in manifest["entries"]:
                    relative = _safe_relative(entry["path"])
                    target = destination / Path(*PurePosixPath(relative).parts)
                    resolved = target.resolve()
                    if destination.resolve() not in resolved.parents:
                        raise FullBackupError("Tentative de sortie de la restauration.")
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
            }
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        finally:
            plain.unlink(missing_ok=True)


def resolve(filename: str) -> Path:
    if not __import__("re").fullmatch(
        r"marvin_full_\d{8}_\d{6}_\d{6}\.mrvfull",
        str(filename or ""),
    ):
        raise FullBackupError("Nom de bundle global invalide.")
    source = BACKUP_DIR / filename
    if source.resolve().parent != BACKUP_DIR.resolve() or not source.is_file():
        raise FileNotFoundError("Bundle global introuvable.")
    return source


def list_backups() -> list[dict[str, Any]]:
    if not BACKUP_DIR.is_dir():
        return []
    return [
        {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat(),
            "encrypted": True,
            "portable": False,
        }
        for path in sorted(
            BACKUP_DIR.glob("marvin_full_*.mrvfull"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
            reverse=True,
        )[:KEEP_LAST]
    ]


def verify(
    filename: str,
    *,
    event_logger: EventLogger = _default_event_logger,
) -> dict[str, Any]:
    source = resolve(filename)
    try:
        with tempfile.TemporaryDirectory(prefix="marvin-full-verify-") as directory:
            result = restore_to(source, Path(directory) / "restored")
        verified = {**result, "destination": None, "verified_only": True}
        event_logger("full_backup_verify", verified)
        return verified
    except Exception as exc:
        event_logger("full_backup_verify", {
            "success": False,
            "error_code": type(exc).__name__,
        })
        raise
