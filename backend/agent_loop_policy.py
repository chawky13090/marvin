"""Politiques déterministes appliquées entre deux itérations du Runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ModelSwitch:
    model: str
    event: dict[str, Any]


def sensitive_tool_model_switch(
    *,
    tool_calls: list[dict[str, Any]],
    active_model: str,
    profile_name: str,
    local_fallback_model: str,
    ultra_cloud_only: bool,
    is_cloud_model: Callable[[str], bool],
    is_sensitive_tool: Callable[[str], bool],
) -> ModelSwitch | None:
    """Impose un repli local avant de réinjecter une donnée sensible."""
    if ultra_cloud_only or not tool_calls or not is_cloud_model(active_model):
        return None
    if not any(
        is_sensitive_tool(call.get("function", {}).get("name", ""))
        for call in tool_calls
    ):
        return None
    return ModelSwitch(
        model=local_fallback_model,
        event={
            "type": "model_info",
            "profile": profile_name,
            "model": local_fallback_model,
            "label": "🔒 Repli local (donnée sensible détectée)",
        },
    )


def build_skill_nudge(
    *,
    skill: dict[str, Any] | None,
    tools_payload: list[dict[str, Any]],
    full_content: str,
) -> list[dict[str, str]]:
    """Construit la relance unique qui force une compétence à agir."""
    available = {
        spec.get("function", {}).get("name")
        for spec in tools_payload
        if spec.get("function", {}).get("name")
    }
    requested = [
        name for name in (skill or {}).get("tools", [])
        if name in available
    ]
    messages: list[dict[str, str]] = []
    if full_content.strip():
        messages.append({"role": "assistant", "content": full_content})
    suffix = (
        f"Utilise EXACTEMENT l'un de ces noms d'outils : {', '.join(requested)}."
        if requested
        else "Utilise l'un des outils fournis."
    )
    messages.append({
        "role": "user",
        "content": (
            "⛔ STOP. Tu as DÉCRIT les étapes au lieu d'AGIR. N'explique plus, "
            "ne réécris pas le plan. Exécute MAINTENANT, via un VRAI appel "
            "d'outil (pas de texte, pas de bloc JSON), l'outil le plus pertinent "
            f"pour la 1ʳᵉ étape — un seul. {suffix}"
        ),
    })
    return messages


def skill_requires_nudge(
    *,
    skill: dict[str, Any] | None,
    tools_payload: list[dict[str, Any]],
    executed_tool_names: set[str],
) -> bool:
    """Relance une compétence uniquement si aucun de ses outils n'a encore agi."""
    available = {
        spec.get("function", {}).get("name")
        for spec in tools_payload
        if spec.get("function", {}).get("name")
    }
    requested = {
        name for name in (skill or {}).get("tools", [])
        if name in available
    }
    return bool(requested) and not bool(requested & executed_tool_names)


def build_empty_response_nudge(*, required_tool_names: set[str]) -> dict[str, str]:
    """Construit l'unique relance autorisée après une sortie modèle vide."""
    required = ", ".join(sorted(required_tool_names))
    requirement = (
        f" Il reste au moins un outil obligatoire à exécuter : {required}."
        if required
        else ""
    )
    return {
        "role": "user",
        "content": (
            "Ta réponse précédente ne contient ni texte utile ni appel d'outil."
            f"{requirement} Réponds maintenant à la demande initiale : émets un appel "
            "d'outil natif si une preuve est requise, sinon livre directement une "
            "réponse utile. Ne décris pas une action future et ne reste pas silencieux."
        ),
    }


def should_suppress_model_text(
    *,
    has_blocking_outcomes: bool,
    required_tool_names: set[str],
    executed_tool_names: set[str],
) -> bool:
    """Masque un brouillon tant qu'une preuve ou un gate obligatoire manque."""
    return has_blocking_outcomes or bool(
        required_tool_names - executed_tool_names
    )


def render_blocking_outcomes(outcomes: dict[str, dict[str, Any]]) -> str | None:
    """Produit un refus explicite lorsqu'un reçu Forge reste négatif."""
    if not outcomes:
        return None
    details: list[str] = []
    for failed_tool, receipt in outcomes.items():
        report = receipt.get("test_report")
        failed_steps = receipt.get("failed_steps") or (
            report.get("failed_steps") if isinstance(report, dict) else []
        ) or []
        reason = (
            receipt.get("error")
            or receipt.get("message")
            or "gate de qualité non validé"
        )
        suffix = (
            f" Étapes en échec : {', '.join(map(str, failed_steps))}."
            if failed_steps
            else ""
        )
        details.append(f"- `{failed_tool}` : {reason}.{suffix}")
    return (
        "## Validation non obtenue\n\n"
        "Je ne peux pas annoncer que le code ou les tests ont réussi : "
        "le dernier reçu Forge est négatif.\n\n"
        + "\n".join(details)
        + "\n\nLe livrable reste refusé tant qu'une correction suivie d'un "
        "nouveau reçu `production_ready=true` n'a pas été observée."
    )
