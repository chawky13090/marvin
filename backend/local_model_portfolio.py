"""Politique persistante du portefeuille local autonome de Marvin.

Le moteur peut proposer et télécharger des modèles allowlistés. Il ne supprime
jamais un modèle : la suppression reste une décision humaine distincte.
"""
from __future__ import annotations

from copy import deepcopy
import os
import subprocess
from typing import Any

import database as db
import local_model_policy


SETTING_KEY = "local_model_portfolio_policy"
SCHEMA = "marvin.local-model-portfolio-policy/1.0"
DEFAULT_POLICY: dict[str, Any] = {
    "schema": SCHEMA,
    "enabled": True,
    "auto_download": False,
    "download_network": "unmetered",
    "max_disk_gb": 25,
    "min_free_disk_gb": 10,
    "maintained_roles": list(local_model_policy.PORTFOLIO_ROLES),
    "activate_after_validation": True,
    "delete_requires_confirmation": True,
}


def _bounded_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def normalize_policy(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    policy = deepcopy(DEFAULT_POLICY)
    policy["enabled"] = bool(raw.get("enabled", policy["enabled"]))
    policy["auto_download"] = bool(raw.get("auto_download", policy["auto_download"]))
    network = str(raw.get("download_network") or policy["download_network"])
    policy["download_network"] = network if network in {"unmetered", "any", "manual"} else "unmetered"
    policy["max_disk_gb"] = _bounded_int(
        raw.get("max_disk_gb"), minimum=5, maximum=500, default=25,
    )
    policy["min_free_disk_gb"] = _bounded_int(
        raw.get("min_free_disk_gb"), minimum=5, maximum=200, default=10,
    )
    roles = raw.get("maintained_roles")
    if isinstance(roles, list):
        allowed = set(local_model_policy.PORTFOLIO_ROLES)
        normalized = list(dict.fromkeys(str(role) for role in roles if str(role) in allowed))
        if normalized:
            policy["maintained_roles"] = normalized
    policy["activate_after_validation"] = True
    policy["delete_requires_confirmation"] = True
    return policy


def get_policy() -> dict[str, Any]:
    return normalize_policy(db.get_setting(SETTING_KEY))


def network_cost() -> str:
    """Retourne ``unmetered``, ``metered`` ou ``unknown`` sans accès réseau sortant."""
    if os.name != "nt":
        return "unknown"
    command = (
        "$p=[Windows.Networking.Connectivity.NetworkInformation,"
        "Windows.Networking.Connectivity,ContentType=WindowsRuntime]::"
        "GetInternetConnectionProfile();"
        "if($null -eq $p){'unknown'}else{$p.GetConnectionCost().NetworkCostType.ToString()}"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            creationflags=0x08000000,
            check=False,
        )
        value = (result.stdout or "").strip().casefold()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if value in {"unrestricted", "unknown"}:
        return "unmetered" if value == "unrestricted" else "unknown"
    if value in {"fixed", "variable"}:
        return "metered"
    return "unknown"


def save_policy(value: Any) -> dict[str, Any]:
    policy = normalize_policy(value)
    db.set_setting(SETTING_KEY, policy)
    return policy


def evaluate(recommendation: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    effective = normalize_policy(policy if policy is not None else get_policy())
    roles = set(effective["maintained_roles"])
    installed = set(recommendation.get("installed") or [])
    downloads: list[dict[str, Any]] = []
    cumulative = 0
    max_bytes = effective["max_disk_gb"] * local_model_policy.GIB
    free_bytes = int(recommendation.get("disk_free_bytes") or 0)
    reserve_bytes = effective["min_free_disk_gb"] * local_model_policy.GIB
    for item in recommendation.get("downloads") or []:
        covered_roles = sorted(roles.intersection(item.get("roles") or []))
        if not covered_roles or local_model_policy.canonical_name(item.get("model")) in installed:
            continue
        size = int(item.get("size_bytes") or 0)
        allowed = (
            size > 0
            and cumulative + size <= max_bytes
            and (not free_bytes or free_bytes - cumulative - size >= reserve_bytes)
        )
        downloads.append({**item, "roles": covered_roles, "policy_allowed": allowed})
        if allowed:
            cumulative += size
    missing_roles = [
        role for role in effective["maintained_roles"]
        if not (recommendation.get("portfolio", {}).get(role) or {}).get("selected")
    ]
    current_network = network_cost()
    network_allowed = (
        effective["download_network"] == "any"
        or (
            effective["download_network"] == "unmetered"
            and current_network == "unmetered"
        )
    )
    queue = [item["model"] for item in downloads if item["policy_allowed"]]
    return {
        "policy": effective,
        "missing_roles": missing_roles,
        "downloads": downloads,
        "network_cost": current_network,
        "network_allowed": network_allowed,
        "auto_download_queue": (
            queue
            if effective["enabled"] and effective["auto_download"] and network_allowed
            else []
        ),
        "estimated_download_bytes": cumulative,
        "deletion_planned": False,
    }


def schedule_download(evaluation: dict[str, Any]) -> dict[str, Any] | None:
    """Planifie la file autorisée; aucun effet si elle est vide ou déjà active."""
    queue = evaluation.get("auto_download_queue") or []
    if not queue:
        return None
    import local_model_installer

    return local_model_installer.start(list(queue), confirmed=True)
