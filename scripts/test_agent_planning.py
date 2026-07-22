"""Regressions de compilation déterministe du plan de tour."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_planning as planning


def _contract(*forced_tools: str) -> dict:
    return {
        "execution_budget": {"max_tool_steps": 16, "max_wall_seconds": 1800},
        "forced_tools": list(forced_tools),
        "resolved": {
            "effort": "deep",
            "autonomy": "execute",
            "privacy": "auto",
            "evidence": "standard",
            "review": "verify",
            "interaction": "stream",
        },
    }


def main() -> int:
    messages = [{"role": "user", "content": "reprends la mission"}]
    workspace = {
        "tool": "code_workspace_control",
        "mission_id": "mission-42",
        "action": "resume",
    }
    with (
        patch.object(planning, "tool_suppression_reason", return_value=None),
        patch.object(planning, "wants_command_text_only", return_value=False),
        patch.object(planning, "wants_model_council", return_value=True),
        patch.object(planning, "workspace_followup", return_value=workspace),
        patch.object(
            planning.cortex,
            "compile_contract",
            return_value=_contract("ai_code_forge", "code_workspace_start"),
        ),
    ):
        plan = planning.compile_turn_plan(messages, "Reprends la mission", {"effort": "deep"})

    assert plan.workspace_mission_id == "mission-42"
    assert plan.workspace_action == "resume"
    assert plan.max_tool_steps == 16
    assert plan.max_wall_seconds == 1800
    assert "code_workspace_control" in plan.required_tool_names
    assert "ai_model_council" in plan.required_tool_names
    assert "ai_code_forge" not in plan.required_tool_names
    assert "code_workspace_start" not in plan.required_tool_names
    assert plan.workspace_norm == "reprends la mission"

    with (
        patch.object(planning, "tool_suppression_reason", return_value="explicit_no_tools"),
        patch.object(planning, "wants_command_text_only", return_value=True),
        patch.object(planning, "wants_model_council", return_value=True),
        patch.object(planning, "workspace_followup") as workspace_followup,
        patch.object(
            planning.cortex,
            "compile_contract",
            return_value=_contract("web_search"),
        ),
    ):
        suppressed = planning.compile_turn_plan(messages, "Donne seulement la commande")

    assert suppressed.command_text_only is True
    assert suppressed.tool_suppression == "explicit_no_tools"
    assert suppressed.required_tool_names == set()
    assert suppressed.workspace_route is None
    workspace_followup.assert_not_called()

    explicit = planning.compile_turn_plan(
        [{"role": "user", "content": "utilise net_ping"}],
        "utilise net_ping",
        {"effort": "instant"},
    )
    assert "net_ping" in explicit.explicit_tool_names

    import agent

    assert callable(agent._compile_turn_plan)
    print("Agent Planning OK - intentions, Workspace, Cortex, budgets et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
