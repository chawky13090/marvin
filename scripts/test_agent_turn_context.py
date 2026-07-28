"""Régressions de la préparation déterministe du contexte d'un tour."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_turn_context import prepare_agent_context


async def main() -> int:
    messages = [
        {"role": "user", "content": "ancien"},
        {"role": "assistant", "content": "réponse"},
        {"role": "user", "content": "actuel"},
    ]
    settings = {
        "history_depth": "2",
        "permission_level": "3",
        "document_identity": {"auteur": "Chaouki", "vide": ""},
    }

    async def paths(_arguments):
        return {"documents": r"C:\Documents"}

    prepared = await prepare_agent_context(
        messages=messages,
        conversation_id="conv-1",
        profile_name="agent",
        cortex_plan={"explicit_axes": [], "resolved": {"autonomy": "execute"}},
        tool_suppression=None,
        required_tool_names={"web_search", "calculator"},
        max_context_messages=20,
        default_permission_level=2,
        model_profiles={"agent": {"tools": True}},
        get_setting=settings.get,
        get_memories=lambda: [
            {"id": "active", "content": "mémoire"},
            {"id": "expired", "content": "mémoire expirée"},
        ],
        get_conversation=lambda _id: {"project_id": "project-1"},
        get_project=lambda _id: {
            "name": "Production",
            "instructions": "Toujours tester.",
        },
        to_ollama_messages=lambda value: [dict(item) for item in value],
        build_system_prompt=lambda memories, permission: (
            f"base:{len(memories)}:{permission}"
        ),
        cortex_prompt_block=lambda _plan: ":cortex",
        get_real_paths=paths,
        filter_memories=lambda memories: [
            memory for memory in memories if memory["id"] != "expired"
        ],
    )
    assert prepared.overflow == [messages[0]]
    assert prepared.permission_level == 3
    assert prepared.use_tools is True
    assert "calculator, web_search" in prepared.system_prompt
    assert "Toujours tester." in prepared.system_prompt
    assert "Chaouki" in prepared.system_prompt

    first_turn = await prepare_agent_context(
        messages=[{"role": "user", "content": "bonjour"}],
        conversation_id="conv-2",
        profile_name="chat",
        cortex_plan={"explicit_axes": [], "resolved": {"autonomy": "execute"}},
        tool_suppression=None,
        required_tool_names=set(),
        max_context_messages=20,
        default_permission_level=2,
        model_profiles={"chat": {"tools": True}},
        get_setting=lambda _key: None,
        get_memories=lambda: [],
        get_conversation=lambda _id: None,
        get_project=lambda _id: None,
        to_ollama_messages=lambda value: [dict(item) for item in value],
        build_system_prompt=lambda _memories, _permission: "base",
        cortex_prompt_block=lambda _plan: "",
        get_real_paths=paths,
    )
    assert [item["role"] for item in first_turn.ollama_messages] == [
        "assistant",
        "tool",
        "user",
    ]
    path_payload = json.loads(first_turn.ollama_messages[1]["content"])
    assert path_payload["type"] == "system_paths_discovery"

    suppressed = await prepare_agent_context(
        messages=[{"role": "user", "content": "quiz"}],
        conversation_id="conv-3",
        profile_name="chat",
        cortex_plan={
            "explicit_axes": ["autonomy"],
            "resolved": {"autonomy": "advise"},
        },
        tool_suppression="quiz_answer",
        required_tool_names=set(),
        max_context_messages=20,
        default_permission_level=2,
        model_profiles={"chat": {"tools": True}},
        get_setting=lambda _key: (_ for _ in ()).throw(RuntimeError("db")),
        get_memories=lambda: (_ for _ in ()).throw(RuntimeError("db")),
        get_conversation=lambda _id: None,
        get_project=lambda _id: None,
        to_ollama_messages=lambda value: [dict(item) for item in value],
        build_system_prompt=lambda memories, permission: (
            f"base:{len(memories)}:{permission}"
        ),
        cortex_prompt_block=lambda _plan: "",
        get_real_paths=paths,
    )
    assert suppressed.permission_level == 2
    assert suppressed.use_tools is False
    assert "MODE RÉPONSE DIRECTE" in suppressed.system_prompt
    assert len(suppressed.ollama_messages) == 1

    invalid_depth = await prepare_agent_context(
        messages=messages,
        conversation_id="conv-4",
        profile_name="chat",
        cortex_plan={"explicit_axes": [], "resolved": {"autonomy": "execute"}},
        tool_suppression=None,
        required_tool_names=set(),
        max_context_messages=20,
        default_permission_level=2,
        model_profiles={"chat": {"tools": True}},
        get_setting=lambda key: -4 if key == "history_depth" else None,
        get_memories=lambda: None,
        get_conversation=lambda _id: None,
        get_project=lambda _id: None,
        to_ollama_messages=lambda value: [dict(item) for item in value],
        build_system_prompt=lambda memories, _permission: f"memories:{len(memories)}",
        cortex_prompt_block=lambda _plan: "",
    )
    assert invalid_depth.ollama_messages == [messages[-1]]
    assert invalid_depth.overflow == messages[:-1]
    assert invalid_depth.system_prompt == "memories:0"
    print(
        "Agent Turn Context OK - historique, chemins, permissions, projet, identité et outils."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
