"""Régressions de lecture et préparation d'une itération modèle."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_model_step import ModelStepResult, prepare_model_step, stream_model_step
import agent_tool_batch


async def main() -> int:
    async def stream(_client, _url, _request):
        yield SimpleNamespace(kind="thinking", text="raisonnement", tool_calls=[])
        yield SimpleNamespace(kind="text", text="bonjour ", tool_calls=[])
        yield SimpleNamespace(kind="text", text="Marvin", tool_calls=[])
        yield SimpleNamespace(
            kind="tool_calls",
            text="",
            tool_calls=[{"function": {"name": "calculator", "arguments": {}}}],
        )

    result = ModelStepResult()
    events = [
        event
        async for event in stream_model_step(
            client=object(),
            base_url="http://ollama",
            request=object(),
            stream_chat=stream,
            result=result,
            suppress_text=False,
        )
    ]
    assert [event["type"] for event in events] == ["thinking", "text", "text"]
    assert result.content == "bonjour Marvin"
    assert result.tool_calls[0]["function"]["name"] == "calculator"

    blocked = ModelStepResult()
    blocked_events = [
        event
        async for event in stream_model_step(
            client=object(),
            base_url="http://ollama",
            request=object(),
            stream_chat=stream,
            result=blocked,
            suppress_text=True,
        )
    ]
    assert [event["type"] for event in blocked_events] == ["thinking"]
    assert blocked.content == "bonjour Marvin"

    def inject(**kwargs):
        return SimpleNamespace(
            tool_calls=kwargs["tool_calls"]
            + [{"function": {"name": "required", "arguments": {}}}],
            injected=True,
        )

    prepared = prepare_model_step(
        content='{"name":"calculator"}',
        native_tool_calls=[],
        tools_payload=[
            {"function": {"name": "calculator"}},
            {"function": {"name": "required"}},
        ],
        required_tool_names={"required"},
        executed_tool_names=set(),
        step=0,
        max_steps=3,
        required_context=object(),
        salvage_text_tool_calls=lambda _content, allowed: [
            {"function": {"name": "calculator", "arguments": {}}}
        ] if "calculator" in allowed else [],
        inject_required_tool_calls=inject,
    )
    assert [call["function"]["name"] for call in prepared.tool_calls] == [
        "calculator",
        "required",
    ]
    assert prepared.required_injected is True

    # Régression du chemin runtime : les identifiants d'appels doivent être générables.
    assert str(agent_tool_batch.uuid.uuid4())
    print("Agent Model Step OK - streaming, blocage, récupération et outils requis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
