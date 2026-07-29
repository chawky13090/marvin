"""Compilation déterministe du plan d'un tour agentique Marvin.

Cette étape précède tout appel de modèle. Elle transforme la demande et le contrat Cortex
en décisions explicites : outils interdits/imposés, reprise Workspace et budgets. Le LLM
reste libre à l'intérieur de ce plan, sans pouvoir modifier rétroactivement ses contraintes.
"""

from __future__ import annotations

import re
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
_WEB_FOLLOWUP_RE = re.compile(
    r"\b(?:refai[st]?|reprends?|continue|poursuis|approfondis?|renforce|"
    r"plus\s+de\s+(?:sources?|r[ée]sultats?)|maximum\s+de\s+r[ée]sultats?|"
    r"un\s+maximum\s+de\s+r[ée]sultats?)\b"
)
_DEEP_WEB_FOLLOWUP_RE = re.compile(
    r"\b(?:approfondis?|renforce|maximum|max|exhaustif|plus\s+de\s+(?:sources?|r[ée]sultats?))\b"
)
_WEB_HISTORY_RE = re.compile(
    r"\b(?:web\s+search|recherche\s+(?:web|internet|en\s+ligne)|"
    r"cherche\w*\s+sur\s+(?:le\s+)?web|visite\w*\s+(?:le\s+)?site)\b"
)
_WEB_DEICTIC_RE = re.compile(
    r"\b(?:ce\s+sujet|ce\s+point|[àa]\s+ce\s+propos|l[àa]\s+dessus|"
    r"cela|[çc]a|dessus|sur\s+ceci)\b"
)
_GENERIC_WEB_REQUEST_RE = re.compile(
    r"^\s*(?:je\s+te\s+demande\s+)?(?:de\s+)?"
    r"(?:faire|lancer|effectuer)?\s*(?:une\s+)?"
    r"recherche\s+(?:sur\s+le\s+)?(?:web|internet)"
    r"(?:\s+(?:maintenant|simple|s['’]il\s+te\s+pla[îi]t|stp|svp))*"
    r"[\s!?.]*$"
)


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    return str(content or "")


def _contextual_web_requirement(
    messages: list[dict[str, Any]],
    user_query: str,
) -> tuple[str, str] | None:
    current = cortex._normalize_intent_text(
        cloud_routing.strip_accents((user_query or "").casefold())
    )
    is_explicit_web = bool(cortex._EXPLICIT_WEB_RE.search(current))
    is_contextual = bool(
        _WEB_FOLLOWUP_RE.search(current)
        or (is_explicit_web and _WEB_DEICTIC_RE.search(current))
        or (is_explicit_web and _GENERIC_WEB_REQUEST_RE.fullmatch(current))
    )
    if not is_contextual:
        return None
    prior = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
    previous_users = [
        (
            _message_text(item).strip(),
            cloud_routing.strip_accents(_message_text(item).casefold()),
        )
        for item in prior
        if item.get("role") == "user"
    ][-4:]
    matched_query = next((
        raw
        for raw, normalized in reversed(previous_users)
        if raw
        and not _GENERIC_WEB_REQUEST_RE.fullmatch(normalized)
        and not (
            cortex._EXPLICIT_WEB_RE.search(normalized)
            and _WEB_DEICTIC_RE.search(normalized)
        )
        and len(normalized.split()) >= 4
    ), "")
    if not matched_query:
        matched_query = next(
            (raw for raw, normalized in reversed(previous_users) if _WEB_HISTORY_RE.search(normalized)),
            "",
        )
    if not matched_query:
        return None
    return (
        "web_deep_research"
        if _DEEP_WEB_FOLLOWUP_RE.search(current)
        else "web_research",
        matched_query,
    )


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
    contextual_web_query: str


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
        contextual_web = _contextual_web_requirement(messages, user_query)
        if contextual_web:
            required_tool_names.discard("web_research")
            required_tool_names.discard("web_deep_research")
            required_tool_names.add(contextual_web[0])
    contextual_web_query = contextual_web[1] if not tool_suppression and contextual_web else ""

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
        contextual_web_query=contextual_web_query,
    )
