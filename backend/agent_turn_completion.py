"""Finalisation commune d'un tour normal ou arrêté par son budget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class TurnCompletion:
    content: str
    critique: str | None
    events: tuple[str, ...]


async def complete_turn(
    *,
    user_query: str,
    content: str,
    active_model: str,
    conversation_id: str,
    cortex_plan: dict[str, Any],
    runner_state: Any,
    executed_tool_names: set[str],
    stop_reason: str,
    force_review: bool,
    skill: dict[str, Any] | None,
    skill_outcomes: Any,
    tools_spec: list[dict[str, Any]],
    background_tasks: set,
    schedule_learning: bool,
    finalize_answer: Callable[..., Awaitable[Any]],
    script_scanner: Callable[..., list[str]],
    critique_pass: Callable[..., Awaitable[Any]],
    council_escalation: Callable[..., Awaitable[Any]],
    create_message: Callable[..., Any],
    schedule_exchange_learning: Callable[..., Any],
    get_setting: Callable[[str], Any],
    record_recipe_outcome: Callable[..., Any],
    build_provenance: Callable[..., dict[str, Any]],
    encode_sse: Callable[[dict[str, Any]], str],
) -> TurnCompletion:
    """Applique revue, persistance et effets terminaux dans un ordre unique."""
    finalized = await finalize_answer(
        user_query=user_query,
        content=content,
        active_model=active_model,
        force_review=force_review,
        script_scanner=script_scanner,
        critique_pass=critique_pass,
        council_escalation=council_escalation,
    )
    final_content = finalized.content
    events = [encode_sse(event) for event in finalized.events]
    if finalized.council_executed:
        executed_tool_names.add("ai_model_council")

    create_message(conversation_id, "assistant", final_content)
    if schedule_learning:
        schedule_exchange_learning(
            user_query=user_query,
            final_content=final_content,
            active_model=active_model,
            background_tasks=background_tasks,
            get_setting=get_setting,
        )

    skill_event = skill_outcomes.finalize(
        skill=skill,
        runner_state=runner_state,
        user_query=user_query,
        final_content=final_content,
        tools_spec=tools_spec,
        background_tasks=background_tasks,
        encode_sse=encode_sse,
    )
    if skill_event:
        events.append(skill_event)

    try:
        record_recipe_outcome(
            cortex_plan["requested"].get("recipe_id"),
            runner_state.succeeded,
            executed_tool_names,
        )
    except Exception:
        pass
    events.append(
        encode_sse(
            {
                "type": "cortex_provenance",
                "provenance": build_provenance(
                    cortex_plan,
                    active_model,
                    executed_tool_names,
                    critique=bool(finalized.critique),
                    answer=final_content,
                    conversation_id=conversation_id,
                    budget_usage=runner_state.budget_usage(stop_reason),
                ),
            }
        )
    )
    events.append(encode_sse({"type": "done"}))
    return TurnCompletion(
        content=final_content,
        critique=finalized.critique,
        events=tuple(events),
    )
