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
    r"recherche\s+plus\s+profond\w*|creuse\s+(?:davantage|plus)|"
    r"plus\s+de\s+(?:sources?|r[ée]sultats?)|maximum\s+de\s+r[ée]sultats?|"
    r"un\s+maximum\s+de\s+r[ée]sultats?)\b"
)
_DEEP_WEB_FOLLOWUP_RE = re.compile(
    r"\b(?:approfondis?|renforce|recherche\s+plus\s+profond\w*|"
    r"creuse\s+(?:davantage|plus)|maximum|max|exhaustif|"
    r"plus\s+de\s+(?:sources?|r[ée]sultats?))\b"
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
    r"^\s*(?:oui[\s,;:!-]+)?(?:je\s+te\s+demande\s+)?(?:de\s+)?"
    r"(?:faire|lancer|effectuer)?\s*(?:une\s+)?"
    r"recherche\s+(?:sur\s+le\s+)?(?:web|internet)"
    r"(?:\s+(?:maintenant|simple|s['’]il\s+te\s+pla[îi]t|stp|svp))*"
    r"[\s!?.]*$"
)
_GENERIC_ACTION_FOLLOWUP_RE = re.compile(
    r"^\s*(?:oui|vas[- ]?y|fais[- ]?le|continue|reprends|réessaie|reessaie|"
    r"tu\s+as\s+les?\s+outils?|utilise\s+(?:donc\s+)?les?\s+outils?|pourtant)\b",
    re.IGNORECASE,
)
_DESKTOP_LIST_RE = re.compile(
    r"\b(?:liste|affiche|montre|donne)\w*\b.{0,60}\b(?:fichiers?|dossiers?)\b"
    r".{0,60}\b(?:bureau|desktop)\b"
)
_TASK_LIST_RE = re.compile(
    r"\b(?:liste|affiche|montre|donne|quelles?)\w*\b.{0,50}\b(?:taches?|tasks?)\b"
)
_NOTE_LIST_RE = re.compile(
    r"\b(?:liste|affiche|montre|donne|quelles?)\w*\b.{0,50}\bnotes?\b"
)
_EMAIL_LIST_RE = re.compile(
    r"\b(?:liste|affiche|montre|donne|quels?)\w*\b.{0,50}\b(?:emails?|mails?|courriels?)\b"
)
_EVENT_LIST_RE = re.compile(
    r"\b(?:liste|affiche|montre|donne|quels?)\w*\b.{0,50}\b"
    r"(?:agenda|calendrier|rendez[- ]?vous|evenements?)\b"
)
_CODE_FILE_DELIVERY_RE = re.compile(
    r"\b(?:script|code|programme)\b.{0,180}\b"
    r"(?:dans|vers|sous)\s+(?:un\s+)?fichier\b|"
    r"\b(?:mets?|enregistre|sauvegarde|écris|ecris)\w*\b.{0,120}\b"
    r"(?:script|code|programme)\b.{0,120}\b(?:fichier|bureau|desktop)\b"
)
_SITE_CRAWL_RE = re.compile(
    r"\b(?:aspire|aspirer|aspiration|crawl|crawler|explore|parcours)\w*\b"
    r".{0,80}\b(?:site|domaine|pages?)\b|"
    r"\b(?:site|domaine)\b.{0,80}\b(?:complet|entier|toutes?\s+les?\s+pages?)\b"
)
_WEB_MEDIA_EXTRACT_RE = re.compile(
    r"\b(?:extrais|extraire|extrait|t[ée]l[ée]charge|r[ée]cup[èe]re)\w*\b"
    r".{0,100}\b(?:images?|photos?|m[ée]dias?|visuels?)\b.{0,100}\b(?:site|page|web)\b|"
    r"\b(?:images?|photos?|m[ée]dias?|visuels?)\b.{0,80}\b(?:du|de\s+la|des)\s+(?:site|page)\b",
    re.IGNORECASE,
)
_PPTX_SITE_DESIGN_RE = re.compile(
    r"(?=.*\b(?:pr[ée]sentation|powerpoint|pptx|diaporama)\b)"
    r"(?=.*\bsite\b)"
    r"(?=.*\b(?:inspir[ée]|design|charte|identit[ée]\s+graphique|style)\w*\b)",
    re.IGNORECASE | re.DOTALL,
)
_EXPLICIT_PPTX_DELIVERY_RE = re.compile(
    r"\b(?:cr[ée]e|cr[ée]er|fais|faire|g[ée]n[èe]re|g[ée]n[ée]rer|veux|souhaite)\w*\b"
    r".{0,100}\b(?:powerpoint|pptx|fichier\s+\.pptx)\b|"
    r"\b(?:powerpoint|pptx|fichier\s+\.pptx)\b.{0,100}"
    r"\b(?:cr[ée]e|fais|g[ée]n[èe]re|veux|souhaite)\w*\b",
    re.IGNORECASE,
)
_NO_FILE_CREATION_RE = re.compile(
    r"\b(?:sans\s+(?:cr[ée]er|g[ée]n[ée]rer)|ne\s+cr[ée]e\s+pas|"
    r"n['’]\s*enregistre\s+pas)\b",
    re.IGNORECASE,
)
_PPTX_REDESIGN_RE = re.compile(
    r"\b(?:refais|refaire|am[ée]liore|embellis|redesign|design|plus\s+(?:joli|beau))\w*\b"
    r".{0,140}\b(?:pr[ée]sentation|powerpoint|pptx|diaporama|cela|ça|ca)\b|"
    r"\b(?:pr[ée]sentation|powerpoint|pptx|diaporama)\b.{0,140}"
    r"\b(?:refais|am[ée]liore|embellis|design|joli|beau)\w*\b",
    re.IGNORECASE,
)
_CONTEXT_ONLY_WEB_RE = re.compile(
    r"^\s*(?:cherche|recherche|regarde|fouille|explore)\w*\s+"
    r"(?:uniquement\s+|aussi\s+)?(?:sur\s+)?(?:les?\s+)?"
    r"(?:r[ée]seaux?\s+sociaux|sources?|sites?|web|internet)"
    r"(?:\s+(?:publics?|officiels?|locaux?|r[ée]cents?))*[\s!?.]*$"
)
_DYNAMIC_RESEARCH_RE = re.compile(
    r"\b(?:derni[èe]res?\s+(?:infos?|nouvelles?|actualit[ée]s?)|"
    r"actualit[ée]s?|en\s+ce\s+moment|aujourd['’]hui|"
    r"statut\s+(?:actuel|des)|situation\s+actuelle)\b"
)
_REFERENTIAL_RESEARCH_RE = re.compile(
    r"\b(?:cible|traite|v[ée]rifie|recherche|approfondis?|creuse)\w*"
    r".{0,40}\b(?:(?:tout|tous|toutes)\s+les?\s+points?|"
    r"points?\s+(?:cit[ée]s?|manquants?)|"
    r"lacunes?|[ée]l[ée]ments?\s+manquants?)\b"
)
_GAP_SECTION_RE = re.compile(
    r"(?:ce\s+qui\s+manque|points?\s+manquants?|lacunes?)",
    re.IGNORECASE,
)
_ENUMERATED_LINE_RE = re.compile(
    r"^\s*(?:[-*]|\d{1,2}[.)])\s+(.{3,240})$",
    re.MULTILINE,
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


def _action_context(messages: list[dict[str, Any]], user_query: str) -> str:
    current = cloud_routing.strip_accents((user_query or "").casefold())
    if not _GENERIC_ACTION_FOLLOWUP_RE.search(current):
        return current
    prior = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
    previous = next(
        (
            _message_text(item)
            for item in reversed(prior)
            if item.get("role") == "user" and _message_text(item).strip()
        ),
        "",
    )
    return cloud_routing.strip_accents(f"{previous}\n{user_query}".casefold())


def _deterministic_action_requirements(
    messages: list[dict[str, Any]],
    user_query: str,
) -> set[str]:
    """Garantit les lectures explicites sans transformer une explication en action."""
    text = _action_context(messages, user_query)
    requirements: set[str] = set()
    if _DESKTOP_LIST_RE.search(text):
        requirements.add("pc_get_real_paths")
    if _TASK_LIST_RE.search(text):
        requirements.add("task_list")
    if _NOTE_LIST_RE.search(text):
        requirements.add("note_list")
    if _EMAIL_LIST_RE.search(text):
        requirements.add("email_list")
    if _EVENT_LIST_RE.search(text):
        requirements.add("event_list")
    if _CODE_FILE_DELIVERY_RE.search(text):
        requirements.add("file_write")
    if _SITE_CRAWL_RE.search(text):
        requirements.add("web_site_crawl")
    if _WEB_MEDIA_EXTRACT_RE.search(text) or _PPTX_SITE_DESIGN_RE.search(text):
        requirements.add("web_media_extract")
    if (
        (_EXPLICIT_PPTX_DELIVERY_RE.search(text) or _PPTX_REDESIGN_RE.search(text))
        and not _NO_FILE_CREATION_RE.search(text)
    ):
        requirements.add("pptx_create")
    return requirements


def _assistant_research_gaps(messages: list[dict[str, Any]]) -> tuple[str, ...]:
    """Extrait des sous-questions bornées, jamais des instructions exécutables."""
    prior = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
    assistant_text = next((
        _message_text(item)
        for item in reversed(prior)
        if item.get("role") == "assistant" and _message_text(item).strip()
    ), "")
    marker = _GAP_SECTION_RE.search(assistant_text)
    if not marker:
        return ()
    section = assistant_text[marker.end(): marker.end() + 6_000]
    values: list[str] = []
    for match in _ENUMERATED_LINE_RE.finditer(section):
        value = " ".join(match.group(1).split()).strip("* ")[:180]
        if value and value not in values:
            values.append(value)
        if len(values) >= 10:
            break
    return tuple(values)


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
        or _REFERENTIAL_RESEARCH_RE.search(current)
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
        and not _CONTEXT_ONLY_WEB_RE.fullmatch(normalized)
        and not _WEB_FOLLOWUP_RE.search(normalized)
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
    modifiers = [
        raw
        for raw, normalized in previous_users
        if _CONTEXT_ONLY_WEB_RE.fullmatch(normalized)
    ][-2:]
    contextual_query = matched_query
    if modifiers:
        contextual_query += "\nContraintes complémentaires : " + " ; ".join(modifiers)
    gaps = _assistant_research_gaps(messages)
    if gaps and _REFERENTIAL_RESEARCH_RE.search(current):
        contextual_query += "\nSous-questions à vérifier : " + " ; ".join(gaps)
    return (
        "web_deep_research"
        if (
            _DEEP_WEB_FOLLOWUP_RE.search(current)
            or _REFERENTIAL_RESEARCH_RE.search(current)
        )
        else "web_research",
        contextual_query,
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
    *,
    llm_native: bool = False,
) -> TurnPlan:
    """Compile les contraintes du tour sans appel réseau, stockage ou modèle."""
    explicit_tool_names = exact_tool_mentions_from_text(
        user_query,
        tool_names=_TOOL_NAMES,
    )
    command_text_only = wants_command_text_only(user_query)
    tool_suppression = tool_suppression_reason(messages, user_query)
    if llm_native:
        # Le modèle choisit la stratégie. Le code conserve uniquement les contraintes
        # explicites négatives, la confidentialité et les budgets de sûreté.
        cortex_plan = cortex.compile_contract(user_query, cortex_contract)
        execution_budget = cortex_plan["execution_budget"]
        native_requirements = (
            set()
            if tool_suppression
            else _deterministic_action_requirements(messages, user_query)
        )
        return TurnPlan(
            explicit_tool_names=set(),
            command_text_only=command_text_only,
            tool_suppression=tool_suppression,
            required_tool_names=native_requirements,
            workspace_norm=cloud_routing.strip_accents(
                (user_query or "").casefold()
            ),
            workspace_route=None,
            workspace_mission_id="",
            workspace_action="",
            cortex_plan=cortex_plan,
            max_tool_steps=int(execution_budget["max_tool_steps"]),
            max_wall_seconds=int(execution_budget["max_wall_seconds"]),
            contextual_web_query="",
        )
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
        required_tool_names.update(
            _deterministic_action_requirements(messages, user_query)
        )
        if (
            "web_research" in required_tool_names
            and _DYNAMIC_RESEARCH_RE.search(workspace_norm)
        ):
            required_tool_names.discard("web_research")
            required_tool_names.add("web_deep_research")
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
