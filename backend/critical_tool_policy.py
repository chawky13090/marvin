"""Manifestes d'effets pour les appels critiques du gateway.

Cette couche ne sélectionne aucun outil. Elle projette uniquement les classifications
historiques déjà autoritaires vers le contrat typé de ``PolicyEngine``.
"""

from __future__ import annotations

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


def manifest_for_critical_call(
    tool_name: str,
    arguments: Mapping[str, Any],
) -> CapabilityManifest:
    """Construit un manifeste conservateur pour un appel déjà classé critique."""
    name = str(tool_name or "").strip()
    lowered = name.casefold()
    if name in _EXTERNAL_COMMUNICATION:
        effects = frozenset({Effect.EXTERNAL_COMMUNICATION})
        scopes = frozenset({Scope.EXTERNAL_ACCOUNT, Scope.INTERNET})
        data_classes = frozenset({DataClass.PERSONAL})
        reversibility = Reversibility.NONE
    elif any(marker in lowered for marker in _DELETE_MARKERS):
        effects = frozenset({Effect.DELETE})
        scopes = frozenset({Scope.HOST})
        data_classes = frozenset({DataClass.INTERNAL})
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

