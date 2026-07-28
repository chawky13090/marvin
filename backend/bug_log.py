"""Journal structuré des exceptions réelles de Marvin."""

from __future__ import annotations

import os
from typing import Any

from structured_logging import StructuredJsonlStore, sanitize


_BUG_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bug_log.jsonl")
_STORE: StructuredJsonlStore | None = None
_STORE_PATH: str | None = None


def _store() -> StructuredJsonlStore:
    global _STORE, _STORE_PATH
    resolved = os.path.abspath(_BUG_LOG_PATH)
    if _STORE is None or _STORE_PATH != resolved:
        _STORE = StructuredJsonlStore.from_environment(
            resolved,
            component="bug_log",
            prefix="BUG_LOG",
            default_retention_days=30,
        )
        _STORE_PATH = resolved
    return _STORE


def _sanitize(obj: Any, max_len: int = 2000) -> Any:
    return sanitize(obj, max_length=max_len)


def log_bug(
    kind: str,
    message: str,
    context: dict | None = None,
    traceback_str: str | None = None,
    conversation_id: str | None = None,
    tool_name: str | None = None,
) -> None:
    """Enregistre une exception en best-effort, sans contenu ni secret brut."""
    try:
        compatibility: dict[str, Any] = {
            "kind": str(kind)[:160],
            "message": str(message)[:1000],
        }
        if tool_name:
            compatibility["tool_name"] = str(tool_name)[:160]
        if conversation_id:
            compatibility["conversation_id"] = str(conversation_id)[:128]
        if context:
            compatibility["context"] = _sanitize(context)
        if traceback_str:
            compatibility["traceback"] = str(traceback_str)[:8000]
        _store().write(
            f"bug.{kind}",
            severity="ERROR",
            outcome="failure",
            trace_id=conversation_id,
            compatibility=compatibility,
        )
    except Exception:
        pass


def _maybe_truncate() -> None:
    """Compatibilité historique : rotation et rétention sont faites à l'écriture."""
    return None


def recent(limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
    try:
        bounded_limit = min(max(int(limit), 1), 1000)
        out: list[dict[str, Any]] = []
        for entry in _store().recent(limit=3000):
            if kind and entry.get("kind") != kind:
                continue
            out.append(entry)
            if len(out) >= bounded_limit:
                break
        return out
    except Exception:
        return []
