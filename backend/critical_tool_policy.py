"""Manifestes d'effets pour les appels critiques du gateway.

Cette couche ne sélectionne aucun outil. Elle projette uniquement les classifications
historiques déjà autoritaires vers le contrat typé de ``PolicyEngine``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from policy_engine import (
    CapabilityManifest,
    DataClass,
    Effect,
    Reversibility,
    Scope,
)


_DELETE_MARKERS = ("delete", "remove", "uninstall", "cleanup", "clean", "forget")
_EXTERNAL_COMMUNICATION = {
    "email_send",
    "email_automation_run",
    "telegram_send",
    "itsm_ticket_create",
}
_REMOTE_EXECUTION_PREFIXES = ("ssh_", "pc_run_", "pc_gui_")
_NETWORK_CHANGE_MARKERS = ("firewall", "network", "vpn", "dns_", "route")
_DESTRUCTIVE_SCRIPT_PATTERN = re.compile(
    r"(?i)\b("
    r"remove-item|remove-itemproperty|clear-content|format-volume|"
    r"stop-process|uninstall-package|winget\s+uninstall|"
    r"rd\s+/s|rmdir\s+/s|del\s+/[a-z]*[sq]|"
    r"reg(?:\.exe)?\s+delete|msiexec(?:\.exe)?\s+/x"
    r")\b"
)
_PERSONAL_DATA_PATTERN = re.compile(
    r"(?i)(appdata|localappdata|userprofile|profile|cookies?|favorites?|bookmarks?)"
)


def approval_summary(tool_name: str, arguments: Mapping[str, Any]) -> str:
    """Décrit l'effet sans exposer le script ou des données sensibles dans l'UI."""
    name = str(tool_name or "").strip()
    script = str(arguments.get("script") or arguments.get("command") or "")
    if name == "pc_run_powershell":
        effects: list[str] = []
        if _DESTRUCTIVE_SCRIPT_PATTERN.search(script):
            effects.append("suppression ou désinstallation")
        if _PERSONAL_DATA_PATTERN.search(script):
            effects.append("données du profil utilisateur")
        if re.search(r"(?i)\bstop-process\b", script):
            effects.append("arrêt forcé de processus")
        detail = ", ".join(dict.fromkeys(effects))
        return (
            f"script PowerShell ({detail})"
            if detail
            else "script PowerShell sur cet appareil"
        )
    if name == "pc_run_command":
        return "commande système sur cet appareil"
    if name == "computer_control" and str(arguments.get("action") or "") == "commit":
        summary = str(arguments.get("commitment_summary") or "").strip()
        return (
            f"confirmation finale : {summary[:300]}"
            if summary
            else "confirmation finale d'un engagement externe"
        )
    if name == "windows_task":
        action = str(arguments.get("action") or "action Windows").strip()
        target = str(
            arguments.get("target")
            or arguments.get("destination")
            or arguments.get("name")
            or arguments.get("pid")
            or "cet appareil"
        ).strip()
        return f"{action} sur {target[:200]}"
    target = str(
        arguments.get("path")
        or arguments.get("host")
        or arguments.get("id")
        or ""
    ).strip()
    return target[:200] or "cet appareil"


def manifest_for_critical_call(
    tool_name: str,
    arguments: Mapping[str, Any],
) -> CapabilityManifest:
    """Construit un manifeste conservateur pour un appel déjà classé critique."""
    name = str(tool_name or "").strip()
    lowered = name.casefold()
    script = str(arguments.get("script") or arguments.get("command") or "")
    destructive_script = (
        lowered.startswith(("pc_run_", "ssh_"))
        and bool(_DESTRUCTIVE_SCRIPT_PATTERN.search(script))
    )
    computer_commit = (
        name == "computer_control"
        and str(arguments.get("action") or "").strip().casefold() == "commit"
    )
    if name in _EXTERNAL_COMMUNICATION or computer_commit:
        effects = frozenset({Effect.EXTERNAL_COMMUNICATION})
        scopes = frozenset({Scope.EXTERNAL_ACCOUNT, Scope.INTERNET})
        data_classes = frozenset({DataClass.PERSONAL})
        reversibility = Reversibility.NONE
    elif any(marker in lowered for marker in _DELETE_MARKERS) or destructive_script:
        effects = frozenset({Effect.DELETE})
        scopes = frozenset({Scope.HOST})
        data_classes = frozenset(
            {DataClass.PERSONAL}
            if _PERSONAL_DATA_PATTERN.search(script)
            else {DataClass.INTERNAL}
        )
        reversibility = Reversibility.NONE
    elif lowered.startswith(_REMOTE_EXECUTION_PREFIXES):
        effects = frozenset({Effect.CODE_EXECUTION})
        scopes = frozenset(
            {Scope.EXTERNAL_ACCOUNT}
            if lowered.startswith("ssh_")
            else {Scope.HOST}
        )
        data_classes = frozenset({DataClass.INTERNAL})
        reversibility = Reversibility.PARTIAL
    elif any(marker in lowered for marker in _NETWORK_CHANGE_MARKERS):
        effects = frozenset({Effect.NETWORK_CHANGE})
        scopes = frozenset({Scope.HOST, Scope.LAN})
        data_classes = frozenset({DataClass.INTERNAL})
        reversibility = Reversibility.PARTIAL
    else:
        effects = frozenset({Effect.INFRASTRUCTURE_WRITE})
        scopes = frozenset({Scope.HOST})
        data_classes = frozenset({DataClass.INTERNAL})
        reversibility = Reversibility.PARTIAL
    return CapabilityManifest(
        name=name,
        effects=effects,
        scopes=scopes,
        data_classes=data_classes,
        reversibility=reversibility,
        idempotent=False,
        sandbox_required=False,
        timeout_seconds=300,
        verified=True,
    )
