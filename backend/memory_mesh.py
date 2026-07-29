"""Métadonnées cognitives sidecar pour les souvenirs Marvin existants."""
from __future__ import annotations

import json
import hashlib
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR


MESH_PATH = Path(DATA_DIR) / "memory_mesh.json"
_LOCK = threading.RLock()
_FRESHNESS_POLICY = {
    "fact": {"review_days": 90, "retention_days": 730},
    "habit": {"review_days": 180, "retention_days": 730},
    "preference": {"review_days": 365, "retention_days": None},
    "user_profile": {"review_days": 365, "retention_days": None},
}


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


def content_sha256(content: str) -> str:
    return hashlib.sha256(str(content).encode("utf-8")).hexdigest()


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
    normalized_category = str(category or "fact").strip().lower()
    policy = _FRESHNESS_POLICY.get(
        normalized_category,
        {"review_days": 90, "retention_days": 365},
    )
    review_after = (
        now + timedelta(days=int(policy["review_days"]))
    ).isoformat()
    expires_at = None
    if kind == "working":
        expires_at = (now + timedelta(days=7)).isoformat()
    elif kind == "episodic":
        expires_at = (now + timedelta(days=365)).isoformat()
    elif policy["retention_days"] is not None:
        expires_at = (
            now + timedelta(days=int(policy["retention_days"]))
        ).isoformat()
    record = {
        "memory_id": str(memory_id),
        "kind": kind,
        "category": normalized_category,
        "source": source[:120],
        "source_history": [],
        "content_sha256": content_sha256(content),
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "sensitive": bool(re.search(r"\b(mail|ssh|client|facture|mot de passe|token|secret)\b", content.lower())),
        "valid_from": now.isoformat(),
        "review_after": review_after,
        "expires_at": expires_at,
        "last_used_at": None,
        "use_count": 0,
        "contradictions": [],
        "updated_at": now.isoformat(),
    }
    with _LOCK:
        mesh = _load()
        previous = mesh.get(str(memory_id), {})
        record["valid_from"] = previous.get("valid_from") or record["valid_from"]
        record["use_count"] = int(previous.get("use_count") or 0)
        record["last_used_at"] = previous.get("last_used_at")
        record["contradictions"] = previous.get("contradictions") or []
        history = [
            str(item)[:120]
            for item in previous.get("source_history") or []
            if str(item).strip()
        ]
        previous_source = str(previous.get("source") or "").strip()
        for item in (previous_source, record["source"]):
            if item and item not in history:
                history.append(item)
        record["source_history"] = history[-20:]
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


def record_contradiction(
    first_id: str | int,
    second_id: str | int,
    *,
    reason_code: str = "manual",
) -> None:
    """Marque symétriquement un conflit sans recopier le contenu des souvenirs."""
    first = str(first_id)
    second = str(second_id)
    if not first or not second or first == second:
        raise ValueError("Deux souvenirs distincts sont requis.")
    if reason_code not in {"manual", "user_correction", "content_conflict"}:
        raise ValueError("Code de contradiction invalide.")
    with _LOCK:
        mesh = _load()
        if first not in mesh or second not in mesh:
            raise KeyError("Souvenir absent du Memory Mesh.")
        detected_at = _now().isoformat()
        for current, other in ((first, second), (second, first)):
            conflicts = [
                item
                for item in mesh[current].get("contradictions") or []
                if isinstance(item, dict) and item.get("memory_id") != other
            ]
            conflicts.append(
                {
                    "memory_id": other,
                    "reason_code": reason_code,
                    "detected_at": detected_at,
                }
            )
            mesh[current]["contradictions"] = conflicts[-50:]
            mesh[current]["updated_at"] = detected_at
        _save(mesh)


def resolve_contradiction(first_id: str | int, second_id: str | int) -> bool:
    """Retire symétriquement un conflit explicitement résolu."""
    first = str(first_id)
    second = str(second_id)
    changed = False
    with _LOCK:
        mesh = _load()
        for current, other in ((first, second), (second, first)):
            if current not in mesh:
                continue
            before = list(mesh[current].get("contradictions") or [])
            after = [
                item
                for item in before
                if not isinstance(item, dict) or item.get("memory_id") != other
            ]
            if after != before:
                mesh[current]["contradictions"] = after
                mesh[current]["updated_at"] = _now().isoformat()
                changed = True
        if changed:
            _save(mesh)
    return changed


def conflicted_ids() -> set[str]:
    with _LOCK:
        records = _load()
    return {
        str(memory_id)
        for memory_id, record in records.items()
        if record.get("contradictions")
    }


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


def stale_ids(*, now: datetime | None = None) -> set[str]:
    """Quarantaine les souvenirs dont la validité doit être reconfirmée."""
    current = now or _now()
    stale: set[str] = set()
    with _LOCK:
        records = _load()
    for memory_id, record in records.items():
        raw_review = record.get("review_after")
        if not raw_review:
            stale.add(str(memory_id))
            continue
        try:
            review = datetime.fromisoformat(str(raw_review))
            if review.tzinfo is None:
                review = review.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            stale.add(str(memory_id))
            continue
        if review <= current:
            stale.add(str(memory_id))
    return stale


def filter_active(
    memories: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Exclut du prompt les souvenirs expirés, sans masquer les entrées legacy sans Mesh."""
    excluded = expired_ids(now=now) | conflicted_ids() | stale_ids(now=now)
    return [
        memory
        for memory in memories
        if str(memory.get("id") or "") not in excluded
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
        "conflicted": sum(1 for item in records if item.get("contradictions")),
        "stale": len(stale_ids()),
    }
