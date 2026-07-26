"""Régressions de la matérialisation des outils obligatoires."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_required_tools import (
    RequiredToolContext,
    inject_required_tool_calls,
)


def main() -> int:
    context = RequiredToolContext(
        user_query="reprends ce script",
        workspace_normalized_query="reprends ce script",
        workspace_mission_id="mission-1",
        workspace_action="resume",
        messages=[
            {"role": "user", "content": "écris un script"},
            {"role": "assistant", "content": "ancien livrable"},
            {"role": "user", "content": "reprends ce script"},
        ],
    )
    ids = iter(["required-a", "required-b"])
    injected = inject_required_tool_calls(
        required_names={"code_workspace_start", "ai_model_council"},
        executed_names=set(),
        tool_calls=[],
        step=0,
        max_steps=10,
        context=context,
        call_id_factory=lambda: next(ids),
    )
    assert injected.injected_names == (
        "ai_model_council",
        "code_workspace_start",
    )
    calls = {item["function"]["name"]: item for item in injected.tool_calls}
    assert calls["ai_model_council"]["function"]["arguments"] == {
        "question": "reprends ce script"
    }
    workspace_request = calls["code_workspace_start"]["function"]["arguments"][
        "request"
    ]
    assert "ancien livrable" in workspace_request

    deferred = inject_required_tool_calls(
        required_names={"ai_model_council"},
        executed_names=set(),
        tool_calls=[
            {
                "id": "web-1",
                "function": {"name": "web_research", "arguments": {}},
            }
        ],
        step=2,
        max_steps=10,
        context=context,
    )
    assert not deferred.injected and len(deferred.tool_calls) == 1

    near_budget = inject_required_tool_calls(
        required_names={"code_workspace_control", "web_deep_research"},
        executed_names=set(),
        tool_calls=[
            {
                "id": "other-1",
                "function": {"name": "calculator", "arguments": {}},
            }
        ],
        step=8,
        max_steps=10,
        context=context,
        call_id_factory=lambda: "required-fixed",
    )
    arguments = {
        call["function"]["name"]: call["function"]["arguments"]
        for call in near_budget.tool_calls
    }
    assert arguments["code_workspace_control"] == {
        "mission_id": "mission-1",
        "action": "resume",
    }
    assert arguments["web_deep_research"] == {"query": "reprends ce script"}

    satisfied = inject_required_tool_calls(
        required_names={"ai_model_council", "long_task_start"},
        executed_names={"ai_model_council"},
        tool_calls=[
            {
                "id": "long-1",
                "function": {"name": "long_task_start", "arguments": {}},
            }
        ],
        step=9,
        max_steps=10,
        context=context,
    )
    assert not satisfied.injected
    print(
        "Agent Required Tools OK - contrats, autonomie, budget, Workspace et dédoublonnage."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
