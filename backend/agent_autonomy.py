"""Autorisation autonome temporaire, explicite et révocable."""

from __future__ import annotations

import time
from typing import Any

import audit


SETTING_KEY = "agent_autonomy_grant"
MODES = frozenset({"normal", "auto", "full"})
MAX_DURATION_MINUTES = 8 * 60

# v2.516 — Outils que le mode `auto` n'auto-approuve jamais, quel que soit leur
# tier de risque. Le contrat annoncé de `auto` est « actions locales réversibles » ;
# une exécution en administrateur ne l'est pas, et `config.DANGEROUS_TOOLS` la
# déclare déjà « toujours confirmée ». Le mode `full`, activé explicitement et
# assumé par le propriétaire, continue de les couvrir.
AUTO_MODE_EXCLUDED_TOOLS = frozenset({"pc_run_elevated"})


def current(database: Any) -> dict:
    raw = database.get_setting(SETTING_KEY, {})
    grant = raw if isinstance(raw, dict) else {}
    mode = str(grant.get("mode") or "normal")
    if mode not in MODES or mode == "normal":
        return {
            "mode": "normal",
            "active": False,
            "expires_at": None,
            "persistence": "revoked",
        }
    if mode == "full":
        return {
            "mode": "full",
            "active": True,
            "expires_at": None,
            "created_at": grant.get("created_at"),
            "persistence": "until_revoked",
        }
    expires_at = float(grant.get("expires_at") or 0)
    if expires_at <= time.time():
        return {
            "mode": "normal",
            "active": False,
            "expires_at": None,
            "persistence": "expired",
        }
    return {
        "mode": mode,
        "active": True,
        "expires_at": expires_at,
        "created_at": grant.get("created_at"),
        "persistence": "temporary",
    }


def configure(database: Any, mode: str, duration_minutes: int = 60) -> dict:
    normalized = str(mode or "").strip().lower()
    if normalized not in MODES:
        raise ValueError("Mode autonome invalide.")
    if normalized == "normal":
        now = time.time()
        grant = {
            "mode": "normal",
            "expires_at": 0,
            "created_at": now,
            "revoked_at": now,
            "persistence": "revoked",
        }
    elif normalized == "full":
        grant = {
            "mode": "full",
            "created_at": time.time(),
            "expires_at": None,
            "revoked_at": None,
            "persistence": "until_revoked",
        }
    else:
        duration = min(max(int(duration_minutes), 5), MAX_DURATION_MINUTES)
        now = time.time()
        grant = {
            "mode": normalized,
            "created_at": now,
            "expires_at": now + duration * 60,
            "revoked_at": None,
            "persistence": "temporary",
        }
    database.set_setting(SETTING_KEY, grant)
    effective = current(database)
    audit.log_action(
        "agent_autonomy_configure",
        {
            "mode": effective["mode"],
            "active": effective["active"],
            "expires_at": effective["expires_at"],
            "persistence": effective["persistence"],
        },
        {"success": True},
        source="settings_ui",
    )
    return effective


def allows(mode: str, risk_tier: int, tool_name: str | None = None) -> bool:
    if mode == "full":
        return True
    if mode != "auto":
        return False
    if tool_name and str(tool_name) in AUTO_MODE_EXCLUDED_TOOLS:
        return False
    return int(risk_tier) <= 3
