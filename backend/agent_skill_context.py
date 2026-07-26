"""Construction sûre du bloc prompt associé à une compétence Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SkillPromptContext:
    prompt: str
    valid: bool
    requires_agent_profile: bool


def build_skill_prompt_context(
    system_prompt: str,
    skill: dict[str, Any] | None,
    *,
    get_golden_trace: Callable[[str], dict[str, Any] | None],
    resources_prompt_block: Callable[[str], str],
) -> SkillPromptContext:
    """Ajoute méthode, golden path et ressources sans faire échouer le tour."""
    if not isinstance(skill, dict):
        return SkillPromptContext(system_prompt, False, False)
    name = skill.get("name")
    description = skill.get("description")
    body = skill.get("body")
    if not all(isinstance(value, str) and value.strip() for value in (name, description, body)):
        return SkillPromptContext(system_prompt, False, False)

    related = skill.get("related")
    related_names = (
        [value for value in related if isinstance(value, str) and value.strip()]
        if isinstance(related, list)
        else []
    )
    related_line = (
        "\nCompétences liées que tu peux enchaîner si besoin : "
        + ", ".join(related_names)
        + "."
        if related_names
        else ""
    )
    prompt = system_prompt + (
        f"\n\n## 📋 Compétence activée : {name}\n"
        f"Quand : {description}\n\n{body}{related_line}\n\n"
        "### Mode opératoire agentique (IMPÉRATIF)\n"
        "1. AGIS MAINTENANT : exécute le PREMIER outil pertinent via un VRAI appel d'outil. "
        "⛔ N'écris JAMAIS un appel d'outil sous forme de texte, de JSON ou de bloc ```...``` — "
        "fais l'appel réel ; le système exécutera l'outil et te renverra le résultat.\n"
        "2. NE déroule PAS tout le plan à l'avance en texte : un seul outil à la fois, puis observe.\n"
        "3. Après CHAQUE outil, LIS le résultat réel et dis ce qu'il signifie — ne suppose JAMAIS le résultat.\n"
        "4. Si une étape échoue ou surprend, AUTO-CORRIGE (essaie une alternative) au lieu d'abandonner ou d'inventer.\n"
        "5. VÉRIFIE que le problème est réellement résolu AVANT de conclure (refais un test quand c'est possible).\n"
        "6. CONCLUS : diagnostic clair + preuve (résultats obtenus) + action recommandée. "
        "Si non résolu, dis-le honnêtement et propose l'étape suivante."
    )

    try:
        golden = get_golden_trace(name)
    except Exception:
        golden = None
    calls = golden.get("calls") if isinstance(golden, dict) else None
    if isinstance(calls, list) and calls:
        steps: list[str] = []
        for index, call in enumerate(calls[:8]):
            if not isinstance(call, dict) or not call.get("tool"):
                continue
            argument_text = f" — {call.get('args')}" if call.get("args") else ""
            steps.append(f"{index + 1}. `{call['tool']}`{argument_text}")
        if steps:
            prompt += (
                "\n\n### ✅ Déroulé DÉJÀ RÉUSSI (exemple à imiter)\n"
                "Pour une demande similaire, cette SÉQUENCE d'outils a fonctionné. "
                "Réutilise-la en adaptant les paramètres au cas présent — "
                "c'est la voie la plus efficace :\n"
                + "\n".join(steps)
            )

    try:
        resources = resources_prompt_block(name)
        if isinstance(resources, str) and resources:
            prompt += resources
    except Exception:
        pass

    tools = skill.get("tools")
    requires_agent = isinstance(tools, list) and any(
        isinstance(value, str) and value for value in tools
    )
    return SkillPromptContext(prompt, True, requires_agent)
