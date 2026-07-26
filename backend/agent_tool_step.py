"""Préparation déterministe d'une étape d'outil du Runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


_CRITICAL_RESULT_FIELDS = frozenset(
    {
        "error",
        "success",
        "message",
        "path",
        "url",
        "title",
        "status",
        "count",
        "hash",
        "result",
        "translated",
        "rows_count",
        "entries_count",
        "pages",
        "total_pages",
    }
)


@dataclass(slots=True)
class PreparedToolCall:
    name: str
    arguments: dict[str, Any]
    read_signature: str = ""


def prepare_tool_call(name: str, raw_arguments: Any) -> PreparedToolCall:
    """Normalise les variantes réellement émises par les modèles."""
    arguments = raw_arguments
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    else:
        arguments = dict(arguments)

    if (
        name == "pc_run_powershell"
        and not arguments.get("script")
        and arguments.get("command")
    ):
        arguments["script"] = arguments.pop("command")
    if name == "ssh_connect" and arguments.get("save"):
        name = "ssh_connection_save"
        arguments.pop("save", None)

    read_signature = ""
    if name == "code_workspace_status":
        read_signature = json.dumps(
            {
                "tool": name,
                "mission_id": str(arguments.get("mission_id") or ""),
            },
            sort_keys=True,
        )
    return PreparedToolCall(
        name=name,
        arguments=arguments,
        read_signature=read_signature,
    )


def inject_internal_context(
    name: str,
    arguments: dict[str, Any],
    conversation_id: str,
) -> dict[str, Any]:
    """Ajoute les identifiants internes que le LLM ne doit jamais inventer."""
    enriched = dict(arguments)
    if name in {"long_task_start", "code_workspace_start"}:
        enriched["_conversation_id"] = conversation_id
    if (
        name in {"screenshot_list", "doc_generate_from_screenshots"}
        and "conversation_id" not in enriched
    ):
        enriched["_conversation_id"] = conversation_id
    return enriched


def compact_tool_result(result: Any, max_chars: int = 4000) -> str:
    """Projette un résultat borné pour le contexte LLM sans toucher au reçu complet."""
    serialized = json.dumps(result, ensure_ascii=False)
    if len(serialized) <= max_chars:
        return serialized
    try:
        if not isinstance(result, dict):
            return serialized[:max_chars] + "…[tronqué]"
        compact: dict[str, Any] = {}
        for key, value in result.items():
            if key in _CRITICAL_RESULT_FIELDS:
                compact[key] = value
            elif isinstance(value, str) and len(value) > 500:
                compact[key] = value[:500] + f"…[{len(value) - 500} chars tronqués]"
            elif isinstance(value, list) and len(value) > 20:
                compact[key] = value[:20] + [f"…+{len(value) - 20} éléments"]
            else:
                compact[key] = value
        return json.dumps(compact, ensure_ascii=False)
    except (TypeError, ValueError):
        return serialized[:max_chars] + "…[tronqué]"
