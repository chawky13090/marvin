"""Mission OS : état durable, checkpoints et preuves d'actions Marvin."""
from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import DATA_DIR
from durable_evidence_store import DurableEvidenceStore


MISSIONS_PATH = Path(DATA_DIR) / "missions.json"
EVENTS_PATH = Path(DATA_DIR) / "mission_events.jsonl"
_LOCK = threading.RLock()
_EVENT_STORE = None
_EVENT_STORE_PATH = None
_SECRET_KEYS = {"password", "token", "secret", "api_key", "private_key", "cookie", "authorization"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_store() -> DurableEvidenceStore:
    global _EVENT_STORE, _EVENT_STORE_PATH
    resolved = str(EVENTS_PATH.resolve())
    if _EVENT_STORE is None or _EVENT_STORE_PATH != resolved:
        _EVENT_STORE = DurableEvidenceStore(resolved, stream_name="marvin.mission.events")
        _EVENT_STORE_PATH = resolved
    return _EVENT_STORE


def _redact(value: Any, key: str = "") -> Any:
    if any(marker in key.lower() for marker in _SECRET_KEYS):
        return "***"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value[:50]]
    if isinstance(value, str):
        return value[:1000]
    return value


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _load() -> list[dict[str, Any]]:
    if not MISSIONS_PATH.exists():
        return []
    try:
        value = json.loads(MISSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _event(event_type: str, mission_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    event = {
        "id": uuid.uuid4().hex,
        "at": _now(),
        "type": event_type,
        "mission_id": mission_id,
        "payload": _redact(payload),
    }
    return _event_store().append(event)


def create_mission(
    *,
    goal: str,
    conversation_id: str,
    tag: str,
    steps: list[str],
    task_ids: list[str | int],
) -> dict[str, Any]:
    mission = {
        "id": uuid.uuid4().hex,
        "goal": goal[:4000],
        "conversation_id": conversation_id,
        "tag": tag,
        "status": "running",
        "steps": [
            {"index": index + 1, "title": title, "task_id": task_ids[index], "status": "pending"}
            for index, title in enumerate(steps)
        ],
        "created_at": _now(),
        "updated_at": _now(),
        "checkpoints": [],
        "success_criteria": ["Toutes les étapes sont terminées", "Aucune action n'est en erreur non traitée"],
    }
    with _LOCK:
        missions = _load()
        previous = deepcopy(missions)
        missions.append(mission)
        _atomic_write(MISSIONS_PATH, missions)
        try:
            _event("mission_created", mission["id"], {"goal": goal, "tag": tag, "steps": steps})
        except Exception:
            _atomic_write(MISSIONS_PATH, previous)
            raise
    return mission


def list_missions(*, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        missions = _load()
    if status:
        missions = [item for item in missions if item.get("status") == status]
    missions.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return missions[: max(1, min(int(limit), 1000))]


def get_mission(mission_id: str) -> dict[str, Any] | None:
    return next((item for item in list_missions(limit=1000) if item.get("id") == mission_id), None)


def find_active(*, conversation_id: str | None = None, tag: str | None = None) -> dict[str, Any] | None:
    return next(
        (
            item for item in list_missions(limit=1000, status="running")
            if (not conversation_id or item.get("conversation_id") == conversation_id)
            and (not tag or item.get("tag") == tag)
        ),
        None,
    )


def _update(
    mission_id: str,
    mutator: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    event_type: str | Callable[[dict[str, Any]], str | None] | None = None,
    event_payload: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    with _LOCK:
        missions = _load()
        previous = deepcopy(missions)
        for index, mission in enumerate(missions):
            if mission.get("id") != mission_id:
                continue
            updated = mutator(deepcopy(mission))
            updated["updated_at"] = _now()
            missions[index] = updated
            _atomic_write(MISSIONS_PATH, missions)
            resolved_event_type = event_type(updated) if callable(event_type) else event_type
            if resolved_event_type:
                payload = event_payload(updated) if callable(event_payload) else (event_payload or {})
                try:
                    _event(resolved_event_type, mission_id, payload)
                except Exception:
                    _atomic_write(MISSIONS_PATH, previous)
                    raise
            return updated
    return None


def checkpoint(mission_id: str, label: str, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    checkpoint_value = {"id": uuid.uuid4().hex, "at": _now(), "label": label[:200], "state": _redact(state or {})}

    def mutate(mission: dict[str, Any]) -> dict[str, Any]:
        mission.setdefault("checkpoints", []).append(checkpoint_value)
        mission["checkpoints"] = mission["checkpoints"][-100:]
        return mission

    return _update(
        mission_id,
        mutate,
        event_type="checkpoint",
        event_payload=checkpoint_value,
    )


def sync_steps(mission_id: str, task_states: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_id = {str(item.get("id")): str(item.get("status") or "pending") for item in task_states}

    def mutate(mission: dict[str, Any]) -> dict[str, Any]:
        for step in mission.get("steps", []):
            step["status"] = by_id.get(str(step.get("task_id")), step.get("status", "pending"))
        statuses = [step.get("status") for step in mission.get("steps", [])]
        if statuses and all(status == "done" for status in statuses):
            mission["status"] = "completed"
        return mission

    return _update(
        mission_id,
        mutate,
        event_type=lambda item: (
            "mission_completed"
            if item.get("status") == "completed"
            else "mission_steps_synced"
        ),
        event_payload=lambda item: {
            "status": item.get("status"),
            "steps": item.get("steps", []),
        },
    )


def stop_mission(mission_id: str, reason: str = "arrêt demandé") -> dict[str, Any] | None:
    return _update(
        mission_id,
        lambda item: {**item, "status": "stopped", "stop_reason": reason[:500]},
        event_type="mission_stopped",
        event_payload={"reason": reason},
    )


def pause_mission(mission_id: str, reason: str = "pause demandée") -> dict[str, Any] | None:
    return _update(
        mission_id,
        lambda item: {**item, "status": "paused", "pause_reason": reason[:500]},
        event_type="mission_paused",
        event_payload={"reason": reason},
    )


def resume_mission(mission_id: str) -> dict[str, Any] | None:
    mission = get_mission(mission_id)
    if not mission or mission.get("status") not in {"paused", "stopped"}:
        return None
    return _update(
        mission_id,
        lambda item: {**item, "status": "running", "pause_reason": None},
        event_type="mission_resumed",
        event_payload={},
    )


def retry_step(mission_id: str, step_index: int) -> dict[str, Any] | None:
    import database as db
    mission = get_mission(mission_id)
    step = next((item for item in (mission or {}).get("steps", []) if item.get("index") == step_index), None)
    if not step:
        return None
    previous_status = str(step.get("status") or "pending")
    db.update_task(str(step["task_id"]), {"status": "pending"})
    def mutate(item):
        for current in item.get("steps", []):
            if current.get("index") == step_index:
                current["status"] = "pending"
        item["status"] = "running"
        return item
    try:
        updated = _update(
            mission_id,
            mutate,
            event_type="step_retry_requested",
            event_payload={"step_index": step_index, "task_id": step["task_id"]},
        )
    except Exception:
        db.update_task(str(step["task_id"]), {"status": previous_status})
        raise
    if updated is None:
        db.update_task(str(step["task_id"]), {"status": previous_status})
    return updated


def record_action(
    *,
    conversation_id: str | None,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    duration_ms: int,
) -> dict[str, Any]:
    mission = find_active(conversation_id=conversation_id) if conversation_id else None
    failed = isinstance(result, dict) and (
        bool(result.get("error"))
        or result.get("success") is False
        or bool(result.get("validation_failed"))
    )
    requires_confirmation = isinstance(result, dict) and bool(result.get("requiresConfirmation"))
    proof = {
        "action_id": uuid.uuid4().hex,
        "tool": tool_name,
        "arguments": _redact(arguments),
        "duration_ms": max(0, int(duration_ms)),
        "outcome": "confirmation_required" if requires_confirmation else "failed" if failed else "succeeded",
        "verified": not failed and not requires_confirmation,
        "result_summary": _redact(result),
        "rollback": rollback_hint(tool_name),
    }
    with _LOCK:
        evidence = _event("action_proof", mission.get("id") if mission else None, {
            "conversation_id": conversation_id,
            **proof,
        })
    return {
        **proof,
        "evidence_sequence": evidence["sequence"],
        "evidence_hash": evidence["record_hash"],
    }


def rollback_hint(tool_name: str) -> str | None:
    if tool_name in {"file_move", "file_rename"}:
        return "Inverser le déplacement ou le renommage avec les chemins avant/après."
    if tool_name in {"event_create", "task_create", "note_create"}:
        return "Supprimer l'objet créé après confirmation."
    if tool_name in {"win_service_action", "pc_run_command", "pc_run_powershell"}:
        return "Restaurer l'état système capturé avant l'action si disponible."
    if tool_name.startswith(("email_send", "telegram_send")):
        return None
    return "Rollback spécifique à définir selon le résultat et l'état initial."


def list_events(*, mission_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    with _LOCK:
        return _event_store().recent(
            max(1, min(int(limit), 5000)),
            predicate=(
                (lambda event: event.get("mission_id") == mission_id)
                if mission_id
                else None
            ),
        )


def evidence_integrity() -> dict[str, Any]:
    return _event_store().verify()
