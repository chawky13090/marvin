"""Central, portable and bounded rollback manifests for ``bulk_rename``."""
from __future__ import annotations

import hashlib
import base64
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psutil
from config import DATA_DIR

SCHEMA_VERSION = 2
LEASE_SECONDS = 300
COMPLETED_RETENTION_SECONDS = 30 * 86400
ABANDONED_RETENTION_SECONDS = 90 * 86400
HEARTBEAT_INTERVAL_SECONDS = 2.0
LEGACY_COMPATIBILITY_SECONDS = 30 * 86400
STORE_ROOT = Path(DATA_DIR) / "rollback" / "bulk-rename"
ACTIVE_STATUSES = frozenset({"planned", "applying", "rolling_back"})
COMPLETED_STATUSES = frozenset({"applied", "rolled_back", "rolled_back_after_failure"})

class RollbackStoreError(RuntimeError):
    pass

@contextmanager
def _store_lock(store_root: Path):
    store_root.mkdir(parents=True, exist_ok=True)
    lock_path = store_root / ".store.lock"
    stream = lock_path.open("a+b")
    try:
        stream.seek(0)
        if stream.tell() == 0 and lock_path.stat().st_size == 0:
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

def _now() -> float:
    return time.time()

def root_fingerprint(root: Path) -> str:
    normalized = os.path.normcase(str(root.resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def manifest_path(run_id: str, *, store_root: Path = STORE_ROOT) -> Path:
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise RollbackStoreError("Identifiant de manifeste invalide.")
    return store_root / f"bulk-rename-{run_id}.json"

def create(root: Path, operations: list[dict[str, str]], run_id: str, *, store_root: Path = STORE_ROOT) -> tuple[Path, dict[str, Any]]:
    now = _now()
    path = manifest_path(run_id, store_root=store_root)
    if path.exists() or path.is_symlink():
        raise RollbackStoreError("Un manifeste portant cet identifiant existe déjà.")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "revision": 1, "tool": "bulk_rename",
        "run_id": run_id, "status": "planned", "created_at": now,
        "heartbeat_at": now, "lease_duration_seconds": LEASE_SECONDS,
        "owner_pid": os.getpid(), "owner_start_time": float(psutil.Process().create_time()),
        "root": str(root.resolve()), "root_fingerprint": root_fingerprint(root),
        "operations": operations,
        "retention": {"completed_seconds": COMPLETED_RETENTION_SECONDS, "abandoned_seconds": ABANDONED_RETENTION_SECONDS},
    }
    _atomic_json(path, payload)
    return path, payload

def save(path: Path, payload: dict[str, Any], *, expected_revision: int | None = None) -> None:
    with _store_lock(path.parent):
        if expected_revision is not None and path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            if int(current.get("revision") or 0) != expected_revision:
                raise RollbackStoreError("Le manifeste a été modifié par un autre processus.")
        payload["revision"] = int(payload.get("revision") or 0) + 1
        _atomic_json(path, payload)

def heartbeat(path: Path, payload: dict[str, Any], *, force: bool = False) -> bool:
    now = _now()
    if not force and now - float(payload.get("heartbeat_at") or 0) < HEARTBEAT_INTERVAL_SECONDS:
        return False
    payload["heartbeat_at"] = now
    save(path, payload, expected_revision=int(payload.get("revision") or 0))
    return True

def set_status(path: Path, payload: dict[str, Any], status: str, **fields: Any) -> None:
    payload.update(fields)
    payload["status"] = status
    payload["heartbeat_at"] = _now()
    save(path, payload, expected_revision=int(payload.get("revision") or 0))

def _validate(payload: dict[str, Any]) -> None:
    operations = payload.get("operations")
    if payload.get("tool") != "bulk_rename" or not isinstance(operations, list) or not operations:
        raise RollbackStoreError("Manifeste bulk_rename invalide.")
    if any(not isinstance(op, dict) or not all(op.get(k) for k in ("old", "new", "temporary")) for op in operations):
        raise RollbackStoreError("Opération de rollback invalide.")

def load(raw_path: str, *, store_root: Path = STORE_ROOT) -> tuple[Path, dict[str, Any], Path]:
    path = Path(raw_path).resolve()
    if not path.is_file() or path.suffix.lower() != ".json":
        raise RollbackStoreError(f"Manifeste de rollback introuvable : {path}")
    payload = json.loads(path.read_text(encoding="utf-8")); _validate(payload)
    root = Path(str(payload.get("root") or "")).resolve()
    if payload.get("schema_version") == SCHEMA_VERSION:
        if path.parent != store_root.resolve() or payload.get("root_fingerprint") != root_fingerprint(root):
            raise RollbackStoreError("Emplacement ou empreinte du manifeste central invalide.")
        return path, payload, root
    if payload.get("version") == 1 and path.parent == (root / ".marvin-rollback").resolve():
        return migrate_legacy_manifest(path, payload, root, store_root=store_root)
    raise RollbackStoreError("Manifeste bulk_rename incompatible.")

def migrate_legacy_manifest(path: Path, payload: dict[str, Any], root: Path, *, store_root: Path = STORE_ROOT) -> tuple[Path, dict[str, Any], Path]:
    source_bytes = path.read_bytes()
    run_id = path.stem.removeprefix("bulk-rename-")
    central, migrated = create(root, list(payload["operations"]), run_id, store_root=store_root)
    migrated.update({"status": str(payload.get("status") or "abandoned"), "created_at": float(payload.get("created_at") or _now()),
                     "legacy": {"source_path": str(path), "migrated_at": _now(), "read_compatibility_until": _now() + LEGACY_COMPATIBILITY_SECONDS,
                                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                                "source_bytes_b64": base64.b64encode(source_bytes).decode("ascii")}})
    save(central, migrated, expected_revision=int(migrated["revision"]))
    path.unlink()
    try: path.parent.rmdir()
    except OSError: pass
    return central, migrated, root

def migrate_legacy_for_root(root: Path, *, store_root: Path = STORE_ROOT) -> list[str]:
    """Inspect only the explicitly supplied root; never scan user disks."""
    legacy = root.resolve() / ".marvin-rollback"; migrated: list[str] = []
    if not legacy.is_dir(): return migrated
    for path in sorted(legacy.glob("bulk-rename-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") == 1 and Path(str(payload.get("root") or "")).resolve() == root.resolve():
            central, _, _ = migrate_legacy_manifest(path, payload, root, store_root=store_root); migrated.append(str(central))
    return migrated

def rollback_legacy_migration(raw_path: str, *, store_root: Path = STORE_ROOT) -> str:
    path, payload, root = load(raw_path, store_root=store_root)
    legacy = payload.get("legacy")
    if not isinstance(legacy, dict) or _now() > float(legacy.get("read_compatibility_until") or 0):
        raise RollbackStoreError("La fenêtre de rollback de migration historique est expirée.")
    destination = Path(str(legacy.get("source_path") or "")).resolve()
    if destination.parent != (root / ".marvin-rollback").resolve() or destination.exists():
        raise RollbackStoreError("Destination historique invalide ou déjà occupée.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = base64.b64decode(str(legacy.get("source_bytes_b64") or ""), validate=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_bytes(source_bytes); os.replace(temporary, destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() == legacy.get("source_sha256"):
        path.unlink()
        return str(destination)
    destination.unlink(missing_ok=True)
    raise RollbackStoreError("La restauration du manifeste historique ne correspond pas à la pré-image.")

def _owner_is_alive(payload: dict[str, Any]) -> bool:
    try:
        process = psutil.Process(int(payload.get("owner_pid")))
        return abs(float(process.create_time()) - float(payload.get("owner_start_time"))) < 1.0
    except (psutil.Error, TypeError, ValueError): return False

def rotate(*, store_root: Path = STORE_ROOT, now: float | None = None) -> dict[str, Any]:
    timestamp = _now() if now is None else now; store_root.mkdir(parents=True, exist_ok=True)
    abandoned: list[str] = []; deleted: list[str] = []; alerts: list[dict[str, Any]] = []
    for path in sorted(store_root.glob("bulk-rename-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8")); status = str(payload.get("status") or "")
        heartbeat_at = float(payload.get("heartbeat_at") or payload.get("created_at") or 0)
        if status in ACTIVE_STATUSES and not (_owner_is_alive(payload) and timestamp - heartbeat_at <= int(payload.get("lease_duration_seconds") or LEASE_SECONDS)):
            set_status(path, payload, "abandoned", abandoned_at=timestamp, notification_required=True); status = "abandoned"; abandoned.append(path.name)
        closed_at = float(payload.get("rolled_back_at") or payload.get("applied_at") or payload.get("created_at") or 0)
        retain_until = float(payload.get("retain_until") or 0)
        if status in COMPLETED_STATUSES and timestamp >= max(closed_at + COMPLETED_RETENTION_SECONDS, retain_until):
            path.unlink(); deleted.append(path.name)
        elif status == "abandoned":
            expires = max(float(payload.get("abandoned_at") or timestamp) + ABANDONED_RETENTION_SECONDS, retain_until)
            remaining_days = max(0, int((expires - timestamp) / 86400))
            reminder = "J-1" if remaining_days <= 1 else "J-7" if remaining_days <= 7 else "J-30" if remaining_days <= 30 else "active"
            alerts.append({"run_id": payload.get("run_id"), "root_fingerprint": payload.get("root_fingerprint"), "rollback_manifest": str(path), "expires_at": expires, "reminder": reminder})
            if payload.get("notification_acknowledged_at") and timestamp >= expires:
                path.unlink(); deleted.append(path.name)
    return {"abandoned": abandoned, "deleted": deleted, "alerts": alerts}

def status(*, store_root: Path = STORE_ROOT) -> dict[str, Any]:
    result = rotate(store_root=store_root)
    return {"manifests": len(list(store_root.glob("bulk-rename-*.json"))), **result}

def acknowledge(raw_path: str, *, retain_until: float | None = None, store_root: Path = STORE_ROOT) -> None:
    path, payload, _ = load(raw_path, store_root=store_root)
    fields: dict[str, Any] = {"notification_acknowledged_at": _now()}
    if retain_until is not None:
        if retain_until <= _now() or retain_until > _now() + 365 * 86400:
            raise RollbackStoreError("Extension de rétention invalide (maximum 365 jours).")
        fields["retain_until"] = retain_until
    set_status(path, payload, str(payload["status"]), **fields)
