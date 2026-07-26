"""Finalisation testable des réponses du Runner agentique."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


CritiquePass = Callable[[str, str, str], Awaitable[str | None]]
CouncilEscalation = Callable[
    [str | None, str],
    Awaitable[tuple[str, dict[str, Any], dict[str, Any], str] | None],
]
ScriptScanner = Callable[[str], list[str]]


@dataclass(slots=True)
class FinalizedAnswer:
    content: str
    events: list[dict[str, Any]] = field(default_factory=list)
    critique: str | None = None
    council_executed: bool = False


async def finalize_answer(
    *,
    user_query: str,
    content: str,
    active_model: str,
    force_review: bool,
    script_scanner: ScriptScanner,
    critique_pass: Callable[..., Awaitable[str | None]],
    council_escalation: CouncilEscalation,
) -> FinalizedAnswer:
    """Applique les contrôles communs sans persistance ni effet de bord externe."""
    events: list[dict[str, Any]] = []

    warnings = script_scanner(content)
    if warnings:
        warning_block = (
            "\n\n---\n⚠️ **Vérification automatique de sécurité** — "
            "points à relire avant d'exécuter ce script :\n"
            + "\n".join(f"- {warning}" for warning in warnings)
        )
        events.append({"type": "text", "text": warning_block})
        content += warning_block

    critique = await critique_pass(
        user_query, content, active_model, force=force_review
    )
    if critique:
        critique_block = "\n\n---\n🧠 **Revue critique (2ᵉ modèle)** :\n" + critique
        events.append({"type": "text", "text": critique_block})
        content += critique_block

    escalation = await council_escalation(critique, content)
    council_executed = escalation is not None
    if escalation:
        call_id, arguments, result, block = escalation
        events.extend(
            [
                {
                    "type": "tool_start",
                    "toolCallId": call_id,
                    "toolName": "ai_model_council",
                    "args": arguments,
                },
                {
                    "type": "tool_end",
                    "toolCallId": call_id,
                    "result": result,
                },
            ]
        )
        if block:
            events.append({"type": "text", "text": block})
            content += block

    return FinalizedAnswer(
        content=content,
        events=events,
        critique=critique,
        council_executed=council_executed,
    )
