"""Finalisation commune d'un tour normal ou arrêté par son budget."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Awaitable, Callable

import bug_log


@dataclass(frozen=True)
class TurnCompletion:
    content: str
    critique: str | None
    events: tuple[str, ...]


_FALSE_WEB_FAILURE_RE = re.compile(
    r"\b(?:"
    r"n['’]ai\s+pas\s+pu\s+(?:effectuer|lancer|faire|interroger)|"
    r"outil\s+(?:de\s+)?recherche\s+web\s+n['’]est\s+pas\s+disponible|"
    r"outil\s+n['’]a\s+pas\s+[ée]t[ée]\s+ex[ée]cut[ée]|"
    r"recherche\s+web\s+n['’]a\s+pas\s+[ée]t[ée]\s+(?:lanc[ée]e|ex[ée]cut[ée])"
    r")\b",
    re.IGNORECASE,
)


def _reconcile_successful_web_result(
    content: str,
    runner_state: Any,
    conversation_id: str,
) -> str:
    """Aligne le texte sur le reçu Web et restitue toutes ses sources."""
    successful = [
        item
        for item in getattr(runner_state, "successful_results", [])
        if item.get("tool") in {"web_search", "web_research", "web_deep_research"}
        and item.get("answer")
    ]
    if not successful:
        return content
    latest = successful[-1]
    contradicted = bool(_FALSE_WEB_FAILURE_RE.search(str(content or "")))
    rendered = str(latest["answer"] if contradicted else content).strip()
    if contradicted:
        bug_log.log_bug(
            "tool_result_contradiction",
            "La réponse du modèle contredisait un reçu Web réussi; synthèse déterministe appliquée.",
            context={"tool": str(latest.get("tool") or "")[:80]},
            conversation_id=conversation_id,
            tool_name=str(latest.get("tool") or "")[:80],
        )
    sources = [
        source
        for source in (latest.get("sources") or [])
        if re.match(r"^https?://", str(source.get("url") or ""), re.IGNORECASE)
    ]
    if sources:
        rendered += (
            f"\n\n### Sources Web ({len(sources)})\n\n"
            + "\n".join(
            f"- [{source['title'] or source['url']}]({source['url']})"
            + (
                " — page lue"
                if source.get("evidence_level") == "page_read"
                else " — connexion requise"
                if source.get("evidence_level") == "access_restricted"
                else " — aperçu du moteur"
            )
            for source in sources
            if source.get("url")
        )
        )
    return rendered


def _reconcile_pending_confirmation(content: str, runner_state: Any) -> str:
    """Empêche une annonce de succès lorsqu'une action attend encore le clic humain."""
    pending = getattr(runner_state, "pending_confirmations", []) or []
    if not pending:
        return content
    latest = pending[-1]
    tool_name = str(latest.get("tool") or "action")
    message = str(latest.get("message") or "Action en attente de confirmation").strip()
    return (
        f"Action en attente de confirmation : `{tool_name}` n'a pas encore été exécuté. "
        "Utilise les boutons Oui/Non affichés dans le chat.\n\n"
        f"{message}"
    )


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
    final_content = _reconcile_successful_web_result(
        finalized.content,
        runner_state,
        conversation_id,
    )
    reconciled_confirmation = _reconcile_pending_confirmation(final_content, runner_state)
    if reconciled_confirmation != final_content:
        bug_log.log_bug(
            "pending_confirmation_contradiction",
            "Réponse terminale remplacée car une action attendait encore une confirmation humaine.",
            context={"tool": str(runner_state.pending_confirmations[-1].get("tool") or "")[:80]},
            conversation_id=conversation_id,
            tool_name=str(runner_state.pending_confirmations[-1].get("tool") or "")[:80],
        )
        final_content = reconciled_confirmation
    events = [encode_sse(event) for event in finalized.events]
    if final_content != finalized.content:
        events.append(encode_sse({
            "type": "answer_final",
            "text": final_content,
        }))
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
