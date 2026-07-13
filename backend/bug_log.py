"""
Marvin — journal des BUGS RÉELS (exceptions non gérées, avec traceback complet).

v2.184 — demandé explicitement (« tout problème doit être logué pour pouvoir le debugger »,
avant une période d'usage intensif sans nouvelle fonctionnalité). Complète `audit.py`
(qui trace QUI a fait QUOI, pour la sécurité/transparence) et `tool_executions` en base
(qui trace succès/échec + timing pour le tableau de bord de fiabilité, mais SANS stack
trace — juste le message d'erreur) : ce module capture le VRAI traceback Python d'une
exception qui s'est échappée quelque part, pour un débogage effectif plus tard sans avoir
à reproduire le bug. Stockage JSONL local (inspectable), best-effort — ne doit JAMAIS
faire échouer l'appelant.
"""
import json
import os
from datetime import datetime

_BUG_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "bug_log.jsonl")
_MAX_KEEP = 2000  # tronque au-delà (garde les plus récents) — les tracebacks sont volumineux

_SECRET_KEY_MARKERS = ("password", "token", "secret", "api_key", "apikey",
                       "credential", "private_key")


def _sanitize(obj, max_len=2000):
    """Filtre les clés sensibles (même liste qu'audit.py) et tronque les valeurs longues —
    généreux (2000 car.) car ce journal sert au débogage, pas juste à un résumé."""
    try:
        if isinstance(obj, dict):
            return {
                k: ("***" if any(s in str(k).lower() for s in _SECRET_KEY_MARKERS)
                    else _sanitize(v, max_len))
                for k, v in obj.items()
            }
        if isinstance(obj, (list, tuple)):
            return [_sanitize(v, max_len) for v in obj[:50]]
        s = str(obj)
        return s[:max_len] + ("…" if len(s) > max_len else "")
    except Exception:
        return "<non sérialisable>"


def log_bug(kind: str, message: str, context: dict = None, traceback_str: str = None,
            conversation_id: str = None, tool_name: str = None):
    """Enregistre un bug réel (best-effort). kind : ex. 'tool_exception', 'http_exception'."""
    try:
        os.makedirs(os.path.dirname(_BUG_LOG_PATH), exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "message": str(message)[:1000],
        }
        if tool_name:
            entry["tool_name"] = tool_name
        if conversation_id:
            entry["conversation_id"] = conversation_id
        if context:
            entry["context"] = _sanitize(context)
        if traceback_str:
            entry["traceback"] = str(traceback_str)[:8000]
        with open(_BUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _maybe_truncate()
    except Exception:
        pass


def _maybe_truncate():
    try:
        if not os.path.exists(_BUG_LOG_PATH):
            return
        if os.path.getsize(_BUG_LOG_PATH) < 8_000_000:
            return
        with open(_BUG_LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > _MAX_KEEP:
            with open(_BUG_LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines[-_MAX_KEEP:])
    except Exception:
        pass


def recent(limit: int = 50, kind: str = None) -> list:
    """Renvoie les derniers bugs (plus récents d'abord), filtrables par kind."""
    try:
        if not os.path.exists(_BUG_LOG_PATH):
            return []
        with open(_BUG_LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()[-3000:]
        out = []
        for ln in reversed(lines):
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if kind and e.get("kind") != kind:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []
