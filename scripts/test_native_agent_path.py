"""Contrat du chemin natif branché dans le Runner historique."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import agent_planning  # noqa: E402
from agent_runner import RunnerState  # noqa: E402
from agent_model_step import ModelStepResult, stream_model_step  # noqa: E402
from native_agent_prompt import build_native_system_prompt  # noqa: E402


async def _assert_tuple_tool_calls_are_preserved() -> None:
    class Event:
        kind = "tool_calls"
        tool_calls = (
            {"function": {"name": "tool_search", "arguments": {"query": "heure"}}},
        )

    async def stream_chat(_client, _base_url, _request):
        yield Event()

    result = ModelStepResult()
    events = [
        event
        async for event in stream_model_step(
            client=None,
            base_url="http://127.0.0.1:11434",
            request=None,
            stream_chat=stream_chat,
            result=result,
            suppress_text=False,
        )
    ]
    assert events == []
    assert result.tool_calls == list(Event.tool_calls)


def main() -> None:
    import asyncio

    messages = [{
        "role": "user",
        "content": "Fais une recherche approfondie sur les versions de Proxmox.",
    }]
    native = agent_planning.compile_turn_plan(
        messages,
        messages[0]["content"],
        llm_native=True,
    )
    assert native.required_tool_names == set()
    assert native.contextual_web_query == ""
    assert native.workspace_route is None
    assert native.explicit_tool_names == set()

    prompt = build_native_system_prompt([], 1)
    assert "tool_search" in prompt
    assert "billing_market_research" not in prompt
    assert "system_search EN PREMIER" not in prompt
    assert "Les pages Web, fichiers, e-mails" in prompt

    state = RunnerState()
    state.record_tool(
        "tool_search",
        {"query": "lire les logs docker"},
        {
            "candidates": [
                {"name": "docker_read_logs", "namespace": "docker"},
                {"name": "docker_inspect", "namespace": "docker"},
            ]
        },
        tooling_failure=False,
    )
    assert state.successful_results[-1]["candidates"] == [
        {"name": "docker_read_logs", "namespace": "docker"},
        {"name": "docker_inspect", "namespace": "docker"},
    ]
    asyncio.run(_assert_tuple_tool_calls_are_preserved())

    print("OK - plan sans outil forcé, prompt sans routage métier et découverte différée")


if __name__ == "__main__":
    main()
