"""Lecture et préparation d'une itération modèle du Runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable


@dataclass
class ModelStepResult:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


async def stream_model_step(
    *,
    client: Any,
    base_url: str,
    request: Any,
    stream_chat: Callable[..., AsyncIterator[Any]],
    result: ModelStepResult,
    suppress_text: bool,
) -> AsyncIterator[dict[str, Any]]:
    """Projette thinking/texte en événements UI et collecte les appels natifs."""
    async for event in stream_chat(client, base_url, request):
        if event.kind == "thinking":
            yield {"type": "thinking", "text": event.text}
        elif event.kind == "text":
            result.content += event.text
            if not suppress_text:
                yield {"type": "text", "text": event.text}
        elif event.kind == "tool_calls":
            calls = event.tool_calls
            # Le transport normalise volontairement les appels en tuple immuable.
            # Accepter les deux formes évite de supprimer silencieusement tous les
            # tool calls natifs reçus d'Ollama.
            result.tool_calls = (
                list(calls)
                if isinstance(calls, (list, tuple))
                else []
            )


@dataclass(frozen=True)
class PreparedModelStep:
    tool_calls: list[dict[str, Any]]
    required_injected: bool


def prepare_model_step(
    *,
    content: str,
    native_tool_calls: list[dict[str, Any]],
    tools_payload: list[dict[str, Any]],
    required_tool_names: set[str],
    executed_tool_names: set[str],
    step: int,
    max_steps: int,
    required_context: Any,
    salvage_text_tool_calls: Callable[
        [str, set[str]],
        list[dict[str, Any]],
    ],
    inject_required_tool_calls: Callable[..., Any],
) -> PreparedModelStep:
    """Récupère les appels textuels puis matérialise les outils contractuels."""
    tool_calls = list(native_tool_calls)
    if not tool_calls and content:
        allowed = {
            spec.get("function", {}).get("name")
            for spec in tools_payload
            if spec.get("function", {}).get("name")
        }
        salvaged = salvage_text_tool_calls(content, allowed)
        if isinstance(salvaged, list) and salvaged:
            tool_calls = salvaged

    injection = inject_required_tool_calls(
        required_names=required_tool_names,
        executed_names=executed_tool_names,
        tool_calls=tool_calls,
        step=step,
        max_steps=max_steps,
        context=required_context,
    )
    return PreparedModelStep(
        tool_calls=list(injection.tool_calls),
        required_injected=bool(injection.injected),
    )
