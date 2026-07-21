"""Mission OS : état durable, checkpoints et preuves d'actions Marvin."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR


MISSIONS_PATH = Path(DATA_DIR) / "missions.json"
EVENTS_PATH = Path(DATA_DIR) / "mission_events.jsonl"
_LOCK = threading.RLock()
_SECRET_KEYS = {"password", "token", "secret", "api_key", "private_key", "cookie", "authorization"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


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
        missions.append(mission)
        _atomic_write(MISSIONS_PATH, missions)
        _event("mission_created", mission["id"], {"goal": goal, "tag": tag, "steps": steps})
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


def _update(mission_id: str, mutator) -> dict[str, Any] | None:
    with _LOCK:
        missions = _load()
        for index, mission in enumerate(missions):
            if mission.get("id") != mission_id:
                continue
            updated = mutator(dict(mission))
            updated["updated_at"] = _now()
            missions[index] = updated
            _atomic_write(MISSIONS_PATH, missions)
            return updated
    return None


def checkpoint(mission_id: str, label: str, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    checkpoint_value = {"id": uuid.uuid4().hex, "at": _now(), "label": label[:200], "state": _redact(state or {})}

    def mutate(mission: dict[str, Any]) -> dict[str, Any]:
        mission.setdefault("checkpoints", []).append(checkpoint_value)
        mission["checkpoints"] = mission["checkpoints"][-100:]
        return mission

    mission = _update(mission_id, mutate)
    if mission:
        _event("checkpoint", mission_id, checkpoint_value)
    return mission


def sync_steps(mission_id: str, task_states: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_id = {str(item.get("id")): str(item.get("status") or "pending") for item in task_states}

    def mutate(mission: dict[str, Any]) -> dict[str, Any]:
        for step in mission.get("steps", []):
            step["status"] = by_id.get(str(step.get("task_id")), step.get("status", "pending"))
        statuses = [step.get("status") for step in mission.get("steps", [])]
        if statuses and all(status == "done" for status in statuses):
            mission["status"] = "completed"
        return mission

    mission = _update(mission_id, mutate)
    if mission and mission.get("status") == "completed":
        _event("mission_completed", mission_id, {"steps": mission.get("steps", [])})
    return mission


def stop_mission(mission_id: str, reason: str = "arrêt demandé") -> dict[str, Any] | None:
    mission = _update(mission_id, lambda item: {**item, "status": "stopped", "stop_reason": reason[:500]})
    if mission:
        _event("mission_stopped", mission_id, {"reason": reason})
    return mission


def pause_mission(mission_id: str, reason: str = "pause demandée") -> dict[str, Any] | None:
    mission = _update(mission_id, lambda item: {**item, "status": "paused", "pause_reason": reason[:500]})
    if mission:
        _event("mission_paused", mission_id, {"reason": reason})
    return mission


def resume_mission(mission_id: str) -> dict[str, Any] | None:
    mission = get_mission(mission_id)
    if not mission or mission.get("status") not in {"paused", "stopped"}:
        return None
    mission = _update(mission_id, lambda item: {**item, "status": "running", "pause_reason": None})
    if mission:
        _event("mission_resumed", mission_id, {})
    return mission


def retry_step(mission_id: str, step_index: int) -> dict[str, Any] | None:
    import database as db
    mission = get_mission(mission_id)
    step = next((item for item in (mission or {}).get("steps", []) if item.get("index") == step_index), None)
    if not step:
        return None
    db.update_task(str(step["task_id"]), {"status": "pending"})
    def mutate(item):
        for current in item.get("steps", []):
            if current.get("index") == step_index:
                current["status"] = "pending"
        item["status"] = "running"
        return item
    updated = _update(mission_id, mutate)
    if updated:
        _event("step_retry_requested", mission_id, {"step_index": step_index, "task_id": step["task_id"]})
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
        _event("action_proof", mission.get("id") if mission else None, {
            "conversation_id": conversation_id,
            **proof,
        })
    return proof


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
    if not EVENTS_PATH.exists():
        return []
    events: list[dict[str, Any]] = []
    with _LOCK:
        for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if mission_id and event.get("mission_id") != mission_id:
                continue
            events.append(event)
    events.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return events[: max(1, min(int(limit), 5000))]
