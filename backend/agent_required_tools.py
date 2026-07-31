"""Matérialisation déterministe des outils obligatoires d'un tour."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable


_CONTEXTUAL_WORKSPACE_RE = re.compile(
    r"\b(?:ce|le|la)\s+(?:script|code|programme|projet)\b"
)
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$")
_MARKDOWN_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")


def _plain_markdown(value: str) -> str:
    value = re.sub(r"[*_`]+", "", value or "")
    value = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", value)
    return " ".join(value.split()).strip(" |#")


def _presentation_arguments(context: RequiredToolContext) -> dict[str, Any]:
    """Construit un repli PPTX borné depuis la synthèse déjà visible du chat."""
    previous = _previous_assistant_content(context.messages)
    requested = re.search(
        r"\b([A-Za-z0-9][A-Za-z0-9._-]{0,120}\.pptx)\b",
        context.user_query,
        re.IGNORECASE,
    )
    output_name = requested.group(1) if requested else "Presentation_Marvin.pptx"
    title = "Présentation Marvin"
    slides: list[dict[str, Any]] = []
    current_title = "Synthèse"
    current_bullets: list[str] = []

    def flush() -> None:
        nonlocal current_bullets
        if current_bullets and len(slides) < 12:
            slides.append({
                "title": current_title[:160],
                "bullets": current_bullets[:8],
            })
        current_bullets = []

    for raw_line in previous.splitlines()[:500]:
        line = raw_line.strip()
        heading = _MARKDOWN_HEADING_RE.match(line)
        if heading:
            clean = _plain_markdown(heading.group(1))
            if clean:
                if title == "Présentation Marvin":
                    title = clean[:160]
                flush()
                current_title = clean
            continue
        listed = _MARKDOWN_LIST_RE.match(line)
        if listed:
            clean = _plain_markdown(listed.group(1))
        elif line.startswith("|") and line.count("|") >= 2 and "---" not in line:
            cells = [_plain_markdown(item) for item in line.strip("|").split("|")]
            clean = " — ".join(item for item in cells if item)
        else:
            clean = ""
        if clean and len(clean) <= 500:
            current_bullets.append(clean)
    flush()
    if not slides:
        slides = [{
            "title": "Demande",
            "bullets": [_plain_markdown(context.user_query)[:500]],
        }]
    return {
        "title": title,
        "subtitle": "Générée par Marvin à partir du contenu vérifié de la conversation",
        "slides": slides,
        "output_path": f"Bureau/{output_name}",
    }


@dataclass(slots=True)
class RequiredToolContext:
    user_query: str
    workspace_normalized_query: str = ""
    workspace_mission_id: str = ""
    workspace_action: str = ""
    messages: list[dict[str, Any]] | None = None
    successful_results: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class RequiredToolInjection:
    tool_calls: list[dict[str, Any]]
    injected_names: tuple[str, ...]

    @property
    def injected(self) -> bool:
        return bool(self.injected_names)


def _previous_assistant_content(
    messages: Iterable[dict[str, Any]] | None,
) -> str:
    if not messages:
        return ""
    items = list(messages)
    for item in reversed(items[:-1]):
        content = str(item.get("content") or "")
        if item.get("role") == "assistant" and content.strip():
            return content
    return ""


def _delivery_filename(context: RequiredToolContext, language: str) -> str:
    requested = re.search(
        r"\b([A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(?:sh|ps1|py|js|go|json))\b",
        context.user_query,
        re.IGNORECASE,
    )
    if requested:
        return requested.group(1)
    suffix = {
        "bash": ".sh",
        "powershell": ".ps1",
        "python": ".py",
        "javascript": ".js",
        "go": ".go",
        "json": ".json",
    }.get(language.casefold(), ".txt")
    return f"livrable_marvin{suffix}"


def _file_delivery_arguments(
    context: RequiredToolContext,
) -> dict[str, Any] | None:
    results = context.successful_results or []
    forge = next(
        (
            item
            for item in reversed(results)
            if item.get("tool") == "ai_code_forge" and item.get("code")
        ),
        None,
    )
    if not forge:
        return None
    language = str(forge.get("language") or "")
    filename = _delivery_filename(context, language)
    return {
        "path": f"Bureau/{filename}",
        "content": str(forge["code"]),
        "overwrite": False,
    }


def _arguments_for(
    name: str,
    context: RequiredToolContext,
) -> dict[str, Any] | None:
    if name in {
        "ai_model_council",
        "ai_cortex_search",
        "ai_research_swarm",
        "ai_adaptive_team",
    }:
        return {"question": context.user_query}
    if name == "ai_code_forge":
        return {"request": context.user_query}
    if name == "code_workspace_start":
        request = context.user_query
        if _CONTEXTUAL_WORKSPACE_RE.search(context.workspace_normalized_query):
            previous = _previous_assistant_content(context.messages)
            if previous:
                request += (
                    "\n\nContexte du livrable précédent à reprendre :\n"
                    + previous[-16_000:]
                )
        return {"request": request}
    if name == "code_workspace_status":
        return {"mission_id": context.workspace_mission_id}
    if name == "code_workspace_control":
        return {
            "mission_id": context.workspace_mission_id,
            "action": context.workspace_action,
        }
    if name in {"web_research", "web_deep_research"}:
        return {"query": context.user_query}
    if name == "web_site_crawl":
        return {"site": context.user_query}
    if name == "file_write":
        return _file_delivery_arguments(context)
    if name == "long_task_start":
        return {"goal": context.user_query}
    if name == "document_generate":
        return {"text": context.user_query, "template": "libre"}
    if name == "pptx_create":
        return _presentation_arguments(context)
    return {}


def inject_required_tool_calls(
    *,
    required_names: set[str],
    executed_names: set[str],
    tool_calls: list[dict[str, Any]],
    step: int,
    max_steps: int,
    context: RequiredToolContext,
    call_id_factory: Callable[[], str] | None = None,
) -> RequiredToolInjection:
    """Ajoute les contrats non satisfaits quand le modèle tente de conclure.

    Un appel obligatoire n'est jamais dupliqué s'il a déjà été exécuté ou émis pendant
    l'étape courante. Tant que le modèle agit et que le budget n'est pas presque épuisé,
    l'injection est différée pour préserver son autonomie.
    """
    present = {
        call.get("function", {}).get("name", "")
        for call in tool_calls
        if isinstance(call, dict)
    }
    missing = required_names - executed_names - present
    should_inject = bool(missing) and (
        not tool_calls or step >= max_steps - 2
    )
    if not should_inject:
        return RequiredToolInjection(tool_calls=tool_calls, injected_names=())

    make_id = call_id_factory or (lambda: f"required-{uuid.uuid4().hex[:12]}")
    result = list(tool_calls)
    injected_names: list[str] = []
    for name in sorted(missing):
        arguments = _arguments_for(name, context)
        if arguments is None:
            continue
        result.append(
            {
                "id": make_id(),
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        )
        injected_names.append(name)
    return RequiredToolInjection(
        tool_calls=result,
        injected_names=tuple(injected_names),
    )
