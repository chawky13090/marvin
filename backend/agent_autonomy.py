"""Autorisation autonome temporaire, explicite et révocable."""

from __future__ import annotations

import time
from typing import Any

import audit


SETTING_KEY = "agent_autonomy_grant"
MODES = frozenset({"normal", "auto", "full"})
MAX_DURATION_MINUTES = 8 * 60


def current(database: Any) -> dict:
    raw = database.get_setting(SETTING_KEY, {})
    grant = raw if isinstance(raw, dict) else {}
    mode = str(grant.get("mode") or "normal")
    expires_at = float(grant.get("expires_at") or 0)
    if mode not in MODES or mode == "normal" or expires_at <= time.time():
        return {"mode": "normal", "active": False, "expires_at": None}
    return {
        "mode": mode,
        "active": True,
        "expires_at": expires_at,
        "created_at": grant.get("created_at"),
    }


def configure(database: Any, mode: str, duration_minutes: int = 60) -> dict:
    normalized = str(mode or "").strip().lower()
    if normalized not in MODES:
        raise ValueError("Mode autonome invalide.")
    if normalized == "normal":
        grant = {"mode": "normal", "expires_at": 0, "created_at": time.time()}
    else:
        duration = min(max(int(duration_minutes), 5), MAX_DURATION_MINUTES)
        now = time.time()
        grant = {
            "mode": normalized,
            "created_at": now,
            "expires_at": now + duration * 60,
        }
    database.set_setting(SETTING_KEY, grant)
    effective = current(database)
    audit.log_action(
        "agent_autonomy_configure",
        {
            "mode": effective["mode"],
            "active": effective["active"],
            "expires_at": effective["expires_at"],
        },
        {"success": True},
        source="settings_ui",
    )
    return effective


def allows(mode: str, risk_tier: int) -> bool:
    if mode == "full":
        return True
    return mode == "auto" and int(risk_tier) <= 3
