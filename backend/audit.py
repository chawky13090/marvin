"""Journal d'audit structuré des actions de Marvin.

L'API historique est conservée. Les écritures sont best-effort : une panne du journal
ne doit jamais faire échouer l'action métier.
"""

from __future__ import annotations

import os
from typing import Any

import api_observability
from structured_logging import StructuredJsonlStore, sanitize


_AUDIT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "audit.jsonl")
_STORE: StructuredJsonlStore | None = None
_STORE_PATH: str | None = None


def _store() -> StructuredJsonlStore:
    global _STORE, _STORE_PATH
    resolved = os.path.abspath(_AUDIT_PATH)
    if _STORE is None or _STORE_PATH != resolved:
        _STORE = StructuredJsonlStore.from_environment(
            resolved,
            component="audit",
            prefix="AUDIT",
            default_retention_days=90,
        )
        _STORE_PATH = resolved
    return _STORE


def log_action(
    tool: str,
    args: dict | None = None,
    result: Any = None,
    source: str = "chat",
    request_id: str | None = None,
) -> None:
    """Enregistre une action : chat | ui | proactif | cron | agent."""
    try:
        failed = isinstance(result, dict) and (
            bool(result.get("error")) or result.get("success") is False
        )
        compatibility: dict[str, Any] = {
            "tool": str(tool)[:160],
            "source": str(source)[:80],
            "ok": not failed,
        }
        if isinstance(result, dict):
            if result.get("error"):
                compatibility["error"] = str(result["error"])[:200]
            elif result.get("success") is False:
                verdict = (result.get("final_review") or {}).get("verdict")
                compatibility["error"] = str(
                    verdict or "Résultat marqué en échec par le contrôle qualité."
                )[:200]
            elif result.get("requiresConfirmation"):
                compatibility["ok"] = None
                compatibility["pending"] = True
            elif result.get("message"):
                compatibility["result_message"] = str(result["message"])[:200]
        if args:
            filtered = {key: value for key, value in dict(args).items() if key != "confirmed"}
            compatibility["args"] = sanitize(filtered, max_length=120)
        _store().write(
            f"tool.{tool}",
            severity="ERROR" if failed else "INFO",
            outcome=(
                "failure"
                if failed
                else ("pending" if compatibility.get("pending") else "success")
            ),
            trace_id=request_id or api_observability.current_request_id(),
            compatibility=compatibility,
        )
    except Exception:
        pass


def _maybe_truncate() -> None:
    """Compatibilité historique : rotation et rétention sont faites à l'écriture."""
    return None


def recent(limit: int = 100, source: str | None = None) -> list[dict[str, Any]]:
    """Renvoie les dernières actions, plus récentes d'abord."""
    try:
        bounded_limit = min(max(int(limit), 1), 1000)
        out: list[dict[str, Any]] = []
        for entry in _store().recent(limit=3000):
            if source and entry.get("source") != source:
                continue
            out.append(entry)
            if len(out) >= bounded_limit:
                break
        return out
    except Exception:
        return []


def stats() -> dict[str, Any]:
    items = recent(limit=2000)
    by_source: dict[str, int] = {}
    errors = 0
    for entry in items:
        source = str(entry.get("source", "?"))
        by_source[source] = by_source.get(source, 0) + 1
        if entry.get("ok") is False:
            errors += 1
    return {"total": len(items), "errors": errors, "by_source": by_source}


def clear() -> bool:
    return _store().clear()
