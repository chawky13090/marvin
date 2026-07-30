"""Régressions des politiques terminales et inter-itérations du Runner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_budget_completion import synthesize_budget_answer
import agent
from agent_loop_policy import (
    _NATIVE_TOOL_CALL_LIMITS,
    build_action_execution_nudge,
    build_computer_action_nudge,
    build_empty_response_nudge,
    build_skill_nudge,
    promises_unexecuted_action,
    requires_computer_action_nudge,
    render_blocking_outcomes,
    render_latest_web_result,
    retryable_cloud_model_error,
    should_suppress_model_text,
    skill_requires_nudge,
    sensitive_tool_model_switch,
)
from agent_transport import OllamaHTTPError


async def main() -> int:
    assert _NATIVE_TOOL_CALL_LIMITS["computer_control"] == 24
    # Régression du chemin Skill chat -> agent : la liste doit exister au runtime.
    assert agent.AUTO_MODE_FALLBACKS

    switch = sensitive_tool_model_switch(
        tool_calls=[{"function": {"name": "email_read"}}],
        active_model="cloud/model",
        profile_name="agent",
        local_fallback_model="local/model",
        ultra_cloud_only=False,
        is_cloud_model=lambda model: model.startswith("cloud/"),
        is_sensitive_tool=lambda name: name.startswith("email_"),
    )
    assert switch and switch.model == "local/model"
    assert sensitive_tool_model_switch(
        tool_calls=[{"function": {"name": "email_read"}}],
        active_model="cloud/model",
        profile_name="agent",
        local_fallback_model="local/model",
        ultra_cloud_only=True,
        is_cloud_model=lambda _model: True,
        is_sensitive_tool=lambda _name: True,
    ) is None

    nudge = build_skill_nudge(
        skill={"tools": ["email_read", "unknown"]},
        tools_payload=[{"function": {"name": "email_read"}}],
        full_content="Je vais lire.",
    )
    assert nudge[0]["role"] == "assistant"
    assert "email_read" in nudge[-1]["content"]
    assert skill_requires_nudge(
        skill={"tools": ["email_read"]},
        tools_payload=[{"function": {"name": "email_read"}}],
        executed_tool_names=set(),
    ) is True
    assert skill_requires_nudge(
        skill={"tools": ["email_read"]},
        tools_payload=[{"function": {"name": "email_read"}}],
        executed_tool_names={"email_read"},
    ) is False
    assert skill_requires_nudge(
        skill={"tools": ["unknown"]},
        tools_payload=[{"function": {"name": "email_read"}}],
        executed_tool_names=set(),
    ) is False
    empty_nudge = build_empty_response_nudge(required_tool_names={"web_research"})
    assert empty_nudge["role"] == "user"
    assert "web_research" in empty_nudge["content"]
    assert "ne reste pas silencieux" in empty_nudge["content"]
    assert promises_unexecuted_action(
        "Je lance plusieurs recherches en parallèle.",
        executed_tool_names=set(),
        tools_available=True,
    ) is True
    assert promises_unexecuted_action(
        "J'ai lancé les recherches et voici les sources.",
        executed_tool_names={"web_search"},
        tools_available=True,
    ) is False
    assert promises_unexecuted_action(
        "Je lance des recherches complémentaires.",
        executed_tool_names={"web_research"},
        tools_available=True,
    ) is True
    assert promises_unexecuted_action(
        "Je pense que cette recherche est pertinente.",
        executed_tool_names=set(),
        tools_available=True,
    ) is False
    action_nudge = build_action_execution_nudge(
        available_tool_names={"web_search", "web_research"},
    )
    assert "promesse n'est pas un résultat" in action_nudge[0]["content"]
    assert "web_search" in action_nudge[0]["content"]
    assert requires_computer_action_nudge(
        "Ouvre le site du restaurant et navigue dans le formulaire.",
        executed_tool_names=set(),
        available_tool_names={"computer_control"},
    ) is True
    assert requires_computer_action_nudge(
        "Explique comment fonctionne un navigateur.",
        executed_tool_names=set(),
        available_tool_names={"computer_control"},
    ) is False
    assert requires_computer_action_nudge(
        "Re teste et trouve une solution, tu dois le faire.",
        executed_tool_names=set(),
        available_tool_names={"computer_control"},
        recent_user_queries=[
            "Ouvre le site du restaurant et navigue jusqu'à la réservation.",
            "Re teste et trouve une solution, tu dois le faire.",
        ],
    ) is True
    assert requires_computer_action_nudge(
        "Continue et corrige.",
        executed_tool_names=set(),
        available_tool_names={"computer_control"},
        recent_user_queries=["Corrige le formatage de ce texte."],
    ) is False
    assert requires_computer_action_nudge(
        "Ouvre la page Web.",
        executed_tool_names={"computer_control"},
        available_tool_names={"computer_control"},
        successful_calls=[{
            "tool": "computer_control",
            "args": '{"action": "observe"}',
        }],
    ) is True
    assert requires_computer_action_nudge(
        "Ouvre la page Web.",
        executed_tool_names={"computer_control"},
        available_tool_names={"computer_control"},
        successful_calls=[{
            "tool": "computer_control",
            "args": '{"action": "navigate", "surface": "browser"}',
        }],
    ) is False
    assert "action=navigate" in build_computer_action_nudge()[0]["content"]
    assert "mode actuel" in build_computer_action_nudge()[0]["content"]
    assert should_suppress_model_text(
        has_blocking_outcomes=False,
        required_tool_names={"web_research"},
        executed_tool_names=set(),
    ) is True
    assert should_suppress_model_text(
        has_blocking_outcomes=False,
        required_tool_names={"web_research"},
        executed_tool_names={"web_research"},
    ) is False
    assert should_suppress_model_text(
        has_blocking_outcomes=True,
        required_tool_names=set(),
        executed_tool_names=set(),
    ) is True
    refusal = render_blocking_outcomes({
        "code_forge": {"message": "tests échoués", "failed_steps": ["pytest"]}
    })
    assert refusal and "tests échoués" in refusal and "pytest" in refusal
    assert render_blocking_outcomes({}) is None
    web_receipt = render_latest_web_result([
        {
            "tool": "web_research",
            "answer": "Résultat vérifié.",
            "sources": [{"title": "Source", "url": "https://example.com/page"}],
        }
    ])
    assert web_receipt == (
        "Résultat vérifié.\n\n### Sources\n\n"
        "- [Source](https://example.com/page)"
    )
    assert retryable_cloud_model_error(OllamaHTTPError(402, "quota modèle")) is True
    assert retryable_cloud_model_error(OllamaHTTPError(503, "indisponible")) is True
    assert retryable_cloud_model_error(OllamaHTTPError(401, "auth")) is False
    assert retryable_cloud_model_error(ValueError("entrée invalide")) is False

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def stream(_client, _url, request):
        assert request["tools"] is None
        yield SimpleNamespace(kind="text", text="Synthèse vérifiée.")

    events = [
        event async for event in synthesize_budget_answer(
            stop_reason="step_budget",
            active_model="model",
            system_prompt="system",
            ollama_messages=[],
            options={},
            base_url="http://ollama",
            request_factory=lambda **kwargs: kwargs,
            client_factory=lambda **_kwargs: Client(),
            stream_chat=stream,
        )
    ]
    assert events[-1] == {"type": "_budget_answer", "content": "Synthèse vérifiée."}

    fallback = [
        event async for event in synthesize_budget_answer(
            stop_reason="wall_clock_budget",
            active_model="model",
            system_prompt="system",
            ollama_messages=[],
            options={},
            base_url="http://ollama",
            request_factory=lambda **kwargs: kwargs,
            client_factory=lambda **_kwargs: Client(),
            stream_chat=lambda *_args: (_ for _ in ()).throw(RuntimeError()),
        )
    ]
    assert fallback[-1]["type"] == "_budget_answer"
    assert "continuer" in fallback[-1]["content"]
    print("Agent Loop Policy OK - repli, nudge, refus Forge et budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
