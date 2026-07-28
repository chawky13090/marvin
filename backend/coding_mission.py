"""Durable, resumable state and artifact snapshots for advanced coding missions."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import deliverable_bundle
from config import DATA_DIR
from durable_evidence_store import DurableEvidenceStore
from structured_logging import sanitize_text


ROOT = Path(DATA_DIR) / "coding_missions"
_LOCK = threading.RLock()
_PHASES = (
    "planned", "architected", "implementing", "reviewing", "testing",
    "repairing", "accepted", "failed", "paused",
)
_SECRET_KEYS = {"password", "token", "secret", "api_key", "authorization", "cookie"}


class MissionConflict(RuntimeError):
    """Raised when a stale worker attempts to overwrite a newer revision."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any, key: str = "") -> Any:
    if any(marker in key.casefold() for marker in _SECRET_KEYS):
        return "***"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str):
        return sanitize_text(value, 4000)
    return value


def _directory(mission_id: str) -> Path:
    if (
        not isinstance(mission_id, str)
        or len(mission_id) != 32
        or any(char not in "0123456789abcdef" for char in mission_id)
    ):
        raise ValueError("Identifiant de mission invalide.")
    return ROOT / mission_id


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _event_store(mission_id: str) -> DurableEvidenceStore:
    return DurableEvidenceStore(
        _directory(mission_id) / "events.jsonl",
        stream_name=f"marvin.coding_mission.{mission_id}",
    )


def _event(mission_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = {"at": _now(), "type": event_type, "payload": _redact(payload)}
    return _event_store(mission_id).append(event)


def record_event(
    mission_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a durable engineering-runtime event without mutating mission state."""
    if get(mission_id) is None:
        raise KeyError("Mission de coding introuvable.")
    with _LOCK:
        return _event(mission_id, str(event_type)[:100], payload or {})


def get(mission_id: str) -> dict[str, Any] | None:
    path = _directory(mission_id) / "mission.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def list_missions(*, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    """Return durable coding missions without loading artifact contents."""
    if not ROOT.exists():
        return []
    rows: list[dict[str, Any]] = []
    for directory in ROOT.iterdir():
        if not directory.is_dir() or len(directory.name) != 32:
            continue
        try:
            mission = get(directory.name)
        except ValueError:
            continue
        if not mission or (status and mission.get("status") != status):
            continue
        rows.append(mission)
    rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return rows[: max(1, min(int(limit), 1000))]


def list_events(mission_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    if get(mission_id) is None:
        return []
    return _event_store(mission_id).recent(max(1, min(int(limit), 5000)))


def stream_events(mission_id: str, *, after: int = 0, limit: int = 500) -> dict[str, Any]:
    """Return chronological events with stable line cursors for SSE resumption."""
    if get(mission_id) is None:
        raise KeyError("Mission de coding introuvable.")
    page = _event_store(mission_id).page(
        after=max(0, int(after)),
        limit=max(1, min(int(limit), 1000)),
    )
    return {
        "events": page["records"],
        "cursor": page["cursor"],
        "mission": get(mission_id),
    }


def evidence_integrity(mission_id: str) -> dict[str, Any]:
    if get(mission_id) is None:
        raise KeyError("Mission de coding introuvable.")
    return _event_store(mission_id).verify()


def latest_manifest(mission_id: str) -> list[dict[str, Any]]:
    mission = get(mission_id)
    snapshot_name = (mission or {}).get("latest_snapshot")
    if not snapshot_name:
        return []
    for entry in reversed(list((mission or {}).get("history") or [])):
        if entry.get("snapshot") == snapshot_name:
            return list(entry.get("manifest") or [])
    return []


def create(
    request: str,
    *,
    target_platforms: list[str] | None = None,
    repository: dict[str, Any] | None = None,
    autonomy: str = "supervised",
    budget: dict[str, int] | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    if autonomy not in {"supervised", "autonomous"}:
        raise ValueError("Mode d'autonomie inconnu.")
    requested_budget = budget or {}
    normalized_budget = {
        "time_slice_minutes": max(5, min(int(requested_budget.get(
            "time_slice_minutes", requested_budget.get("max_duration_minutes", 120)
        )), 1_440)),
        # Compatibilité API/UI : ce champ représente une tranche, jamais la durée de vie de la mission.
        "max_duration_minutes": max(5, min(int(requested_budget.get(
            "time_slice_minutes", requested_budget.get("max_duration_minutes", 120)
        )), 1_440)),
        "max_iterations": max(1, min(int(requested_budget.get("max_iterations", 12)), 100)),
        "max_files_changed": max(1, min(int(requested_budget.get("max_files_changed", 50)), 1_000)),
        "max_consecutive_failures": max(1, min(int(requested_budget.get("max_consecutive_failures", 3)), 10)),
    }
    mission_id = uuid.uuid4().hex
    mission = {
        "id": mission_id,
        "request": str(request)[:20_000],
        "status": "running",
        "phase": "planned",
        "revision": 0,
        "target_platforms": list(dict.fromkeys(target_platforms or ["windows", "linux"]))[:4],
        "autonomy": autonomy,
        "completion_policy": "until_success" if autonomy == "autonomous" else "supervised",
        "budget": normalized_budget,
        "repository": _redact(repository or {}),
        "conversation_id": str(conversation_id or "")[:100] or None,
        "validation_policy": {
            "execution_required": True,
            "linux_isolation": "docker",
            "windows_isolation": "windows_sandbox_or_vm",
            "production_ready_requires_all_targets": True,
        },
        "created_at": _now(),
        "updated_at": _now(),
        "latest_snapshot": None,
        "history": [],
    }
    with _LOCK:
        directory = _directory(mission_id)
        directory.mkdir(parents=True, exist_ok=False)
        try:
            _atomic_write(directory / "mission.json", mission)
            _event(mission_id, "created", {
                "target_platforms": mission["target_platforms"],
                "autonomy": autonomy,
                "budget": normalized_budget,
                "repository": mission["repository"],
                "conversation_id": mission["conversation_id"],
            })
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
    return mission


def checkpoint(
    mission_id: str,
    phase: str,
    *,
    state: dict[str, Any] | None = None,
    files: dict[str, str] | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    if phase not in _PHASES:
        raise ValueError(f"Phase de mission inconnue : {phase}")
    with _LOCK:
        mission = get(mission_id)
        if not mission:
            raise KeyError("Mission de coding introuvable.")
        previous_mission = json.loads(json.dumps(mission, ensure_ascii=False))
        revision = int(mission.get("revision") or 0)
        if expected_revision is not None and revision != int(expected_revision):
            raise MissionConflict(f"Révision attendue {expected_revision}, révision courante {revision}.")
        revision += 1
        snapshot_name = None
        snapshot_path: Path | None = None
        previous_snapshot: bytes | None = None
        manifest: list[dict[str, Any]] = []
        if files is not None:
            normalized = {
                deliverable_bundle.normalize_path(path): str(content)
                for path, content in files.items()
            }
            if len(normalized) > deliverable_bundle.MAX_FILES:
                raise deliverable_bundle.BundleError("Trop de fichiers dans le snapshot de mission.")
            total = sum(len(content.encode("utf-8")) for content in normalized.values())
            if total > deliverable_bundle.MAX_BUNDLE_BYTES:
                raise deliverable_bundle.BundleError("Snapshot de mission trop volumineux.")
            manifest = [
                {
                    "path": path,
                    "bytes": len(content.encode("utf-8")),
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
                for path, content in sorted(normalized.items())
            ]
            snapshot_name = f"snapshot-{revision:04d}.json"
            snapshot_path = _directory(mission_id) / "snapshots" / snapshot_name
            previous_snapshot = snapshot_path.read_bytes() if snapshot_path.exists() else None
            _atomic_write(
                snapshot_path,
                {"revision": revision, "phase": phase, "files": normalized, "manifest": manifest},
            )
        entry = {"revision": revision, "at": _now(), "phase": phase,
                 "state": _redact(state or {}), "snapshot": snapshot_name, "manifest": manifest}
        mission["revision"] = revision
        mission["phase"] = phase
        mission["updated_at"] = entry["at"]
        mission["latest_snapshot"] = snapshot_name or mission.get("latest_snapshot")
        mission.setdefault("history", []).append(entry)
        mission["history"] = mission["history"][-200:]
        if phase == "accepted":
            mission["status"] = "completed"
        elif phase == "failed":
            mission["status"] = "failed"
        elif phase == "paused":
            mission["status"] = "paused"
        else:
            mission["status"] = "running"
        mission_path = _directory(mission_id) / "mission.json"
        _atomic_write(mission_path, mission)
        try:
            _event(mission_id, "checkpoint", entry)
        except Exception:
            _atomic_write(mission_path, previous_mission)
            if snapshot_path is not None:
                if previous_snapshot is None:
                    snapshot_path.unlink(missing_ok=True)
                else:
                    temporary = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
                    temporary.write_bytes(previous_snapshot)
                    os.replace(temporary, snapshot_path)
            raise
        return mission


def latest_files(mission_id: str) -> dict[str, str]:
    mission = get(mission_id)
    snapshot_name = (mission or {}).get("latest_snapshot")
    if not snapshot_name:
        return {}
    path = _directory(mission_id) / "snapshots" / str(snapshot_name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in dict(value.get("files") or {}).items()}


def write_delivery_pack(mission_id: str, payload: dict[str, Any]) -> str:
    """Persist the immutable hand-off metadata next to mission snapshots."""
    if get(mission_id) is None:
        raise KeyError("Mission de coding introuvable.")
    path = _directory(mission_id) / "delivery-pack.json"
    previous = path.read_bytes() if path.exists() else None
    _atomic_write(path, _redact(payload))
    try:
        record_event(mission_id, "delivery.pack.created", {
            "path": str(path), "status": payload.get("status"),
            "manifest_count": len(payload.get("manifest") or []),
        })
    except Exception:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(previous)
            os.replace(temporary, path)
        raise
    return str(path)


def read_delivery_pack(mission_id: str) -> dict[str, Any] | None:
    path = _directory(mission_id) / "delivery-pack.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def resume_context(mission_id: str, *, max_chars: int = 100_000) -> dict[str, Any]:
    mission = get(mission_id)
    if not mission:
        raise KeyError("Mission de coding introuvable.")
    files = latest_files(mission_id)
    selected: dict[str, str] = {}
    consumed = 0
    for path, content in files.items():
        if consumed + len(content) > max_chars:
            break
        selected[path] = content
        consumed += len(content)
    return {
        "mission_id": mission_id,
        "request": mission.get("request"),
        "phase": mission.get("phase"),
        "revision": mission.get("revision"),
        "files": selected,
        "truncated": len(selected) != len(files),
    }
