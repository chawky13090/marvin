"""
Journal d'audit des actions de Marvin (inspiré OpenClaw, en mieux : on trace AUSSI la
SOURCE déclencheuse — chat / interface / proactif / cron — pour la transparence et la
sécurité du mode autonome). Stockage en JSONL local (inspectable, git-able), best-effort :
le journal ne doit JAMAIS faire échouer une action.
"""
import json
import os
from datetime import datetime

_AUDIT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "audit.jsonl")
_MAX_KEEP = 5000   # on tronque le fichier au-delà (garde les plus récents)


def log_action(tool: str, args: dict = None, result=None, source: str = "chat"):
    """Enregistre une action (best-effort). source : chat | ui | proactif | cron | agent."""
    try:
        os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
        failed = isinstance(result, dict) and (
            bool(result.get("error")) or result.get("success") is False
        )
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "tool": tool,
            "source": source,
            "ok": not failed,
        }
        if isinstance(result, dict):
            if result.get("error"):
                entry["error"] = str(result["error"])[:200]
            elif result.get("success") is False:
                verdict = (result.get("final_review") or {}).get("verdict")
                entry["error"] = str(verdict or "Résultat marqué en échec par le contrôle qualité.")[:200]
            elif result.get("requiresConfirmation"):
                entry["ok"] = None  # action proposée, en attente de confirmation
                entry["pending"] = True
            elif result.get("message"):
                entry["message"] = str(result["message"])[:200]
        if args:
            try:
                # v2.106 — filtre par SOUS-CHAÎNE (pas égalité stricte) : "password"
                # seul ratait "owner_password", "token" ratait "bot_token"/"access_token",
                # "secret" ratait "client_secret"/"google_client_secret" — autant de vrais
                # secrets qui finissaient en clair dans ce fichier JSONL git-able.
                entry["args"] = {k: str(v)[:120] for k, v in dict(args).items()
                                 if k != "confirmed" and not any(
                                     s in k.lower() for s in
                                     ("password", "token", "secret", "api_key", "apikey",
                                      "credential", "private_key"))}
            except Exception:
                pass
        with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _maybe_truncate()
    except Exception:
        pass


def _maybe_truncate():
    try:
        if not os.path.exists(_AUDIT_PATH):
            return
        # tronque seulement de temps en temps (coût I/O)
        if os.path.getsize(_AUDIT_PATH) < 2_000_000:
            return
        with open(_AUDIT_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > _MAX_KEEP:
            with open(_AUDIT_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines[-_MAX_KEEP:])
    except Exception:
        pass


def recent(limit: int = 100, source: str = None) -> list:
    """Renvoie les dernières actions (plus récentes d'abord), filtrables par source."""
    try:
        if not os.path.exists(_AUDIT_PATH):
            return []
        with open(_AUDIT_PATH, encoding="utf-8") as f:
            lines = f.readlines()[-3000:]
        out = []
        for ln in reversed(lines):
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if source and e.get("source") != source:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def stats() -> dict:
    """Compteurs rapides pour l'UI (total, erreurs, par source)."""
    items = recent(limit=2000)
    by_source, errors = {}, 0
    for e in items:
        by_source[e.get("source", "?")] = by_source.get(e.get("source", "?"), 0) + 1
        if e.get("ok") is False:
            errors += 1
    return {"total": len(items), "errors": errors, "by_source": by_source}


def clear():
    try:
        open(_AUDIT_PATH, "w", encoding="utf-8").close()
    except Exception:
        pass
