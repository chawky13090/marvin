"""Métadonnées cognitives sidecar pour les souvenirs Marvin existants."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR


MESH_PATH = Path(DATA_DIR) / "memory_mesh.json"
_LOCK = threading.RLock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def classify(content: str, category: str = "fact") -> str:
    text = (content or "").lower()
    category = (category or "").lower()
    if category in {"procedure", "skill", "workflow"} or re.search(r"\b(étape|procédure|commande|workflow)\b", text):
        return "procedural"
    if category in {"event", "history", "episode"} or re.search(r"\b(hier|aujourd'hui|le \d{1,2}/\d{1,2})\b", text):
        return "episodic"
    if category in {"working", "temporary"}:
        return "working"
    return "semantic"


def _load() -> dict[str, dict[str, Any]]:
    if not MESH_PATH.exists():
        return {}
    try:
        value = json.loads(MESH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save(value: dict[str, dict[str, Any]]) -> None:
    MESH_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MESH_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, MESH_PATH)


def register(
    memory_id: str | int,
    content: str,
    category: str,
    *,
    source: str = "conversation",
    confidence: float = 0.8,
) -> dict[str, Any]:
    kind = classify(content, category)
    now = _now()
    expires_at = None
    if kind == "working":
        expires_at = (now + timedelta(days=7)).isoformat()
    elif kind == "episodic":
        expires_at = (now + timedelta(days=365)).isoformat()
    record = {
        "memory_id": str(memory_id),
        "kind": kind,
        "source": source[:120],
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "sensitive": bool(re.search(r"\b(mail|ssh|client|facture|mot de passe|token|secret)\b", content.lower())),
        "valid_from": now.isoformat(),
        "expires_at": expires_at,
        "last_used_at": None,
        "use_count": 0,
        "contradictions": [],
        "updated_at": now.isoformat(),
    }
    with _LOCK:
        mesh = _load()
        previous = mesh.get(str(memory_id), {})
        record["use_count"] = int(previous.get("use_count") or 0)
        record["last_used_at"] = previous.get("last_used_at")
        record["contradictions"] = previous.get("contradictions") or []
        mesh[str(memory_id)] = record
        _save(mesh)
    return record


def mark_used(memory_id: str | int) -> dict[str, Any] | None:
    with _LOCK:
        mesh = _load()
        record = mesh.get(str(memory_id))
        if not record:
            return None
        record["use_count"] = int(record.get("use_count") or 0) + 1
        record["last_used_at"] = _now().isoformat()
        record["updated_at"] = record["last_used_at"]
        _save(mesh)
        return record


def list_metadata(*, kind: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        records = list(_load().values())
    if kind:
        records = [item for item in records if item.get("kind") == kind]
    records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return records


def stats() -> dict[str, Any]:
    records = list_metadata()
    by_kind = {kind: sum(1 for item in records if item.get("kind") == kind)
               for kind in ("working", "episodic", "semantic", "procedural")}
    return {
        "total": len(records),
        "by_kind": by_kind,
        "sensitive": sum(1 for item in records if item.get("sensitive")),
        "used": sum(1 for item in records if int(item.get("use_count") or 0) > 0),
    }
