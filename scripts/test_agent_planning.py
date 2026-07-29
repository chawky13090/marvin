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

    for web_query in (
        "donne les derniers infos sur koios.fr en visitant leur site",
        "recherche web sur koios",
    ):
        web_plan = planning.compile_turn_plan(
            [{"role": "user", "content": web_query}],
            web_query,
        )
        assert "web_research" in web_plan.required_tool_names, web_query
    reinforced = planning.compile_turn_plan(
        [{"role": "user", "content": "web search renforcer sur le sujet de koios"}],
        "web search renforcer sur le sujet de koios",
    )
    assert "web_deep_research" in reinforced.required_tool_names
    assert "web_research" not in reinforced.required_tool_names

    for dynamic_query in (
        "statut des feux de foret en France",
        "Effectue une recherche approfondie et vérifiable sur le statut des feux de foret en France",
        "quel est l'état du trafic en Île-de-France",
    ):
        dynamic = planning.compile_turn_plan(
            [{"role": "user", "content": dynamic_query}],
            dynamic_query,
        )
        expected = (
            "web_deep_research"
            if "approfondie" in dynamic_query
            else "web_research"
        )
        assert expected in dynamic.required_tool_names, dynamic_query

    typo_web = planning.compile_turn_plan(
        [{"role": "user", "content": "recherhe web sur kes feux de foret en france"}],
        "recherhe web sur kes feux de foret en france",
    )
    assert "web_research" in typo_web.required_tool_names

    followup_messages = [
        {
            "role": "user",
            "content": "web search renforcer sur le sujet de koios aix-en-provence",
        },
        {"role": "assistant", "content": "Résultats partiels."},
        {
            "role": "user",
            "content": "refait la recherche je veut un maximum de resulats",
        },
    ]
    followup = planning.compile_turn_plan(
        followup_messages,
        followup_messages[-1]["content"],
    )
    assert "web_deep_research" in followup.required_tool_names
    assert followup.contextual_web_query == followup_messages[0]["content"]

    deictic_messages = [
        {
            "role": "user",
            "content": "salut, quel est l'etat des feux de foret en France ?",
        },
        {"role": "assistant", "content": "Une recherche actuelle est nécessaire."},
        {"role": "user", "content": "recherche web a ce sujet"},
    ]
    deictic = planning.compile_turn_plan(
        deictic_messages,
        deictic_messages[-1]["content"],
    )
    assert "web_research" in deictic.required_tool_names
    assert deictic.contextual_web_query == deictic_messages[0]["content"]

    unrelated = planning.compile_turn_plan(
        [
            {"role": "user", "content": "Explique OSPF"},
            {"role": "user", "content": "donne un maximum de résultats"},
        ],
        "donne un maximum de résultats",
    )
    assert not ({"web_research", "web_deep_research"} & unrelated.required_tool_names)

    import agent

    assert callable(agent._compile_turn_plan)
    print("Agent Planning OK - intentions, Workspace, Cortex, budgets et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
