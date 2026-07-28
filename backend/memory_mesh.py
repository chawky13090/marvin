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


class MemoryMeshError(RuntimeError):
    """Signale un sidecar illisible afin d'éviter toute réécriture destructive."""


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
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryMeshError("Memory Mesh illisible.") from exc
    if not isinstance(value, dict):
        raise MemoryMeshError("Le format Memory Mesh est invalide.")
    return value


def _save(value: dict[str, dict[str, Any]]) -> None:
    MESH_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MESH_PATH.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
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


def remove(memory_id: str | int) -> bool:
    """Retire les métadonnées d'un souvenir sans toucher aux autres entrées."""
    with _LOCK:
        mesh = _load()
        removed = mesh.pop(str(memory_id), None) is not None
        if removed:
            _save(mesh)
        return removed


def clear() -> int:
    """Vide le sidecar après nettoyage des stockages de contenu."""
    with _LOCK:
        mesh = _load()
        count = len(mesh)
        if count:
            _save({})
        return count


def expired_ids(*, now: datetime | None = None) -> set[str]:
    """Retourne les souvenirs dont la durée déclarée est effectivement échue."""
    current = now or _now()
    expired: set[str] = set()
    with _LOCK:
        records = _load()
    for memory_id, record in records.items():
        raw_expiry = record.get("expires_at")
        if not raw_expiry:
            continue
        try:
            expiry = datetime.fromisoformat(str(raw_expiry))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if expiry <= current:
            expired.add(str(memory_id))
    return expired


def filter_active(
    memories: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Exclut du prompt les souvenirs expirés, sans masquer les entrées legacy sans Mesh."""
    expired = expired_ids(now=now)
    return [
        memory
        for memory in memories
        if str(memory.get("id") or "") not in expired
    ]


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
