"""Compilation déterministe du plan d'un tour agentique Marvin.

Cette étape précède tout appel de modèle. Elle transforme la demande et le contrat Cortex
en décisions explicites : outils interdits/imposés, reprise Workspace et budgets. Le LLM
reste libre à l'intérieur de ce plan, sans pouvoir modifier rétroactivement ses contraintes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cloud_routing
import cortex
from agent_policy import exact_tool_mentions_from_text
from intent_guard import (
    tool_suppression_reason,
    wants_command_text_only,
    wants_model_council,
    workspace_followup,
)
from tools import TOOLS_SPEC


_TOOL_NAMES = {
    specification.get("function", {}).get("name", "")
    for specification in TOOLS_SPEC
}


@dataclass(slots=True)
class TurnPlan:
    explicit_tool_names: set[str]
    command_text_only: bool
    tool_suppression: str | None
    required_tool_names: set[str]
    workspace_norm: str
    workspace_route: dict[str, Any] | None
    workspace_mission_id: str
    workspace_action: str
    cortex_plan: dict[str, Any]
    max_tool_steps: int
    max_wall_seconds: int


def compile_turn_plan(
    messages: list[dict[str, Any]],
    user_query: str,
    cortex_contract: dict[str, Any] | None = None,
) -> TurnPlan:
    """Compile les contraintes du tour sans appel réseau, stockage ou modèle."""
    explicit_tool_names = exact_tool_mentions_from_text(
        user_query,
        tool_names=_TOOL_NAMES,
    )
    command_text_only = wants_command_text_only(user_query)
    tool_suppression = tool_suppression_reason(messages, user_query)
    required_tool_names = (
        {"ai_model_council"}
        if not tool_suppression and wants_model_council(user_query)
        else set()
    )

    workspace_norm = cloud_routing.strip_accents((user_query or "").casefold())
    workspace_route = None if tool_suppression else workspace_followup(messages, user_query)
    workspace_mission_id = str((workspace_route or {}).get("mission_id") or "")
    workspace_action = str((workspace_route or {}).get("action") or "resume")
    if workspace_route:
        required_tool_names.add(workspace_route["tool"])

    cortex_plan = cortex.compile_contract(user_query, cortex_contract)
    execution_budget = cortex_plan["execution_budget"]
    if not tool_suppression:
        required_tool_names.update(cortex_plan.get("forced_tools") or [])

    if "code_workspace_control" in required_tool_names:
        # Une reprise doit conserver le snapshot et les preuves de la mission existante.
        required_tool_names.discard("ai_code_forge")
        required_tool_names.discard("code_workspace_start")

    return TurnPlan(
        explicit_tool_names=explicit_tool_names,
        command_text_only=command_text_only,
        tool_suppression=tool_suppression,
        required_tool_names=required_tool_names,
        workspace_norm=workspace_norm,
        workspace_route=workspace_route,
        workspace_mission_id=workspace_mission_id,
        workspace_action=workspace_action,
        cortex_plan=cortex_plan,
        max_tool_steps=int(execution_budget["max_tool_steps"]),
        max_wall_seconds=int(execution_budget["max_wall_seconds"]),
    )
