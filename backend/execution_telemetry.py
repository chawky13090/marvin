"""Metadonnees locales, bornees et non textuelles des decisions d'outil."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from typing import Any

from app_version import APP_VERSION


DEFAULT_SELECTOR_VERSION = "kls-main/v1"


def build_routing_context(
    specifications: Sequence[dict[str, Any]],
    *,
    model_name: str,
    profile_name: str,
    get_setting: Callable[[str], Any],
    selector_version: str = DEFAULT_SELECTOR_VERSION,
) -> dict[str, Any]:
    """Construit une preuve minimale sans texte utilisateur ni schema d'outil."""
    enabled = get_setting("local_execution_telemetry")
    if enabled is None:
        enabled = os.getenv("MARVIN_LOCAL_EXECUTION_TELEMETRY", "1")
    if str(enabled).strip().lower() in {"0", "false", "no", "off"}:
        return {"app_version": APP_VERSION}

    names = sorted(
        {
            str(item.get("function", {}).get("name") or "").strip()
            for item in specifications
            if str(item.get("function", {}).get("name") or "").strip()
        }
    )
    canonical = json.dumps(names, ensure_ascii=True, separators=(",", ":"))
    auto_config = get_setting("auto_config")
    runtime_mode = (
        str(auto_config.get("mode") or "unknown")
        if isinstance(auto_config, dict)
        else "unknown"
    )
    return {
        "app_version": APP_VERSION,
        "model_name": str(model_name or "")[:160],
        "runtime_mode": runtime_mode[:32],
        "profile_name": str(profile_name or "")[:32],
        "selector_version": str(selector_version or DEFAULT_SELECTOR_VERSION)[:64],
        "candidate_count": len(names),
        "candidate_set_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
    }
