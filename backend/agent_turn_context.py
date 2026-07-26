"""Préparation déterministe du contexte d'un tour avant skills et rappel sémantique."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class PreparedAgentContext:
    overflow: list[dict[str, Any]]
    ollama_messages: list[dict[str, Any]]
    system_prompt: str
    permission_level: int
    use_tools: bool


async def prepare_agent_context(
    *,
    messages: list[dict[str, Any]],
    conversation_id: str,
    profile_name: str,
    cortex_plan: dict[str, Any],
    tool_suppression: str | bool | None,
    required_tool_names: set[str],
    max_context_messages: int,
    default_permission_level: int,
    model_profiles: dict[str, dict[str, Any]],
    get_setting: Callable[[str], Any],
    get_memories: Callable[[], list[dict[str, Any]]],
    get_conversation: Callable[[str], dict[str, Any] | None],
    get_project: Callable[[Any], dict[str, Any] | None],
    to_ollama_messages: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    build_system_prompt: Callable[[list[dict[str, Any]], int], str],
    cortex_prompt_block: Callable[[dict[str, Any]], str],
    get_real_paths: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
) -> PreparedAgentContext:
    """Construit messages, permissions et prompt de base avec replis non bloquants."""
    try:
        history_depth = int(
            get_setting("history_depth") or max_context_messages
        )
    except Exception:
        history_depth = max_context_messages
    # Le message utilisateur courant doit toujours rester visible, même si un réglage
    # persistant a été corrompu ou saisi à zéro.
    history_depth = max(1, history_depth)
    split_at = max(0, len(messages) - history_depth)
    overflow = messages[:split_at]
    recent = messages[split_at:]
    ollama_messages = to_ollama_messages(recent)

    if len(messages) <= 1 and not tool_suppression and get_real_paths is not None:
        try:
            real_paths = await get_real_paths({})
            if ollama_messages and ollama_messages[-1].get("role") == "user":
                ollama_messages.insert(
                    -1,
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "pc_get_real_paths",
                                    "arguments": {},
                                }
                            }
                        ],
                    },
                )
                ollama_messages.insert(
                    -1,
                    {
                        "role": "tool",
                        "content": json.dumps(
                            {
                                "type": "system_paths_discovery",
                                **real_paths,
                            },
                            ensure_ascii=False,
                        ),
                    },
                )
        except Exception:
            pass

    try:
        memories = get_memories()
    except Exception:
        memories = []
    if not isinstance(memories, list):
        memories = []
    try:
        raw_permission = get_setting("permission_level")
        permission_level = (
            int(raw_permission)
            if raw_permission is not None
            else default_permission_level
        )
    except Exception:
        permission_level = default_permission_level

    advise_only = (
        "autonomy" in cortex_plan.get("explicit_axes", [])
        and cortex_plan["resolved"]["autonomy"] == "advise"
    )
    use_tools = bool(
        model_profiles.get(profile_name, {}).get("tools", True)
        and not tool_suppression
        and (not advise_only or required_tool_names)
    )

    system_prompt = build_system_prompt(memories, permission_level)
    system_prompt += cortex_prompt_block(cortex_plan)
    if tool_suppression:
        system_prompt += (
            "\n\n=== MODE RÉPONSE DIRECTE ===\n"
            "Aucun outil ne doit être appelé pour ce tour. Réponds uniquement au message "
            "de l'utilisateur dans le chat, sans chercher, diagnostiquer, mémoriser ni créer de fichier."
        )
    if required_tool_names:
        system_prompt += (
            "\n\n=== OUTIL(S) IMPOSÉ(S) PAR LE CONTRAT ===\n"
            f"Tu dois obligatoirement exécuter : {', '.join(sorted(required_tool_names))}. "
            "Tu ne peux pas conclure avant leur exécution réelle."
        )

    try:
        conversation = get_conversation(conversation_id)
        project_id = (conversation or {}).get("project_id")
        if project_id:
            project = get_project(project_id)
            instructions = (project or {}).get("instructions") or ""
            if instructions.strip():
                system_prompt += (
                    f"\n\n=== INSTRUCTIONS DU PROJET « {project.get('name', '')} » ===\n"
                    f"{instructions.strip()}\n"
                    "(Ces instructions s'appliquent à toute cette conversation, en plus des règles ci-dessus.)"
                )
    except Exception:
        pass

    try:
        document_identity = get_setting("document_identity")
        if isinstance(document_identity, dict) and any(document_identity.values()):
            identity_lines = "\n".join(
                f"- {key} : {value}"
                for key, value in document_identity.items()
                if value
            )
            system_prompt += (
                "\n\n=== IDENTITÉ DOCUMENT DÉJÀ CONNUE (ne redemande PAS ces infos) ===\n"
                f"{identity_lines}\n"
                "(file_create_pdf/file_create_docx l'appliquent déjà automatiquement en repli — "
                "inutile de la repasser en argument sauf pour LA remplacer pour ce document précis.)"
            )
    except Exception:
        pass

    return PreparedAgentContext(
        overflow=overflow,
        ollama_messages=ollama_messages,
        system_prompt=system_prompt,
        permission_level=permission_level,
        use_tools=use_tools,
    )
