"""Politique déterministe d'autorisation et de dispatch des outils."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from config import (
    CONDITIONAL_TOOL_SAFE_ACTIONS,
    DANGEROUS_TOOLS,
    PERMISSION_SECURE,
    SECURE_BLOCKED_TOOLS,
)


EXECUTION_TOOLS = frozenset(
    {
        "pc_run_command", "pc_run_powershell", "pc_run_elevated",
        "ssh_exec", "ssh_exec_multi", "ssh_write_and_run",
        "ssh_list", "ssh_server_info",
    }
)

ALWAYS_CONFIRM_TOOLS = frozenset(
    {
        "email_send", "email_automation_run", "telegram_send",
        "itsm_ticket_create", "file_delete", "task_delete", "note_delete",
        "event_delete", "memory_delete", "ssh_exec", "ssh_exec_multi",
        "ssh_upload", "ssh_write_and_run", "system_cleanup", "long_task_start",
        "pc_gui_click", "pc_gui_type", "code_workspace_start",
        "code_workspace_control",
    }
) | frozenset(DANGEROUS_TOOLS) | frozenset(CONDITIONAL_TOOL_SAFE_ACTIONS)


def is_parallel_batch_eligible(tool_calls: list[dict[str, Any]]) -> bool:
    """Vrai si un lot d'appels peut s'exécuter en CONCURRENCE sans risque.

    v2.525 — Un lot n'est éligible que si AUCUN de ses appels ne figure dans
    `ALWAYS_CONFIRM_TOOLS`. Deux raisons impératives, pas une préférence :
    (1) `tool_gateway` n'autorise qu'UNE seule approbation active par
    conversation (v2.522) — deux demandes de confirmation concurrentes se
    supplanteraient l'une l'autre ; (2) `postprocess_tool_result` ne déclenche
    la relecture indépendante (`critique_action`, un VRAI appel modèle) que
    pour les outils dangereux — l'exclure garantit qu'aucun appel modèle
    concurrent supplémentaire n'est introduit par cette tranche.

    Simplification déclarée : les outils listés dans
    `CONDITIONAL_TOOL_SAFE_ACTIONS` (ex. `computer_control` en lecture) sont
    exclus par NOM, sans inspecter l'action demandée — un `computer_control`
    en `action="screenshot"` reste donc séquentiel alors qu'il serait sûr en
    parallèle. Granularité par action laissée à une évolution ultérieure : le
    gain principal visé ici (plusieurs lectures indépendantes simultanées)
    n'en dépend pas.
    """
    if len(tool_calls) < 2:
        return False
    for call in tool_calls:
        function = call.get("function") if isinstance(call, dict) else None
        name = str((function or {}).get("name") or "")
        if not name or name in ALWAYS_CONFIRM_TOOLS:
            return False
    return True


Validator = Callable[[str, dict[str, Any]], str | None]
Executor = Callable[
    [str, dict[str, Any], str, str | None],
    Awaitable[dict[str, Any]],
]


@dataclass(slots=True)
class ToolDispatchRequest:
    name: str
    arguments: dict[str, Any]
    conversation_id: str
    request_id: str | None
    permission_level: int
    read_signature: str = ""
    seen_read_signatures: set[str] | None = None
    explicit_names: set[str] | None = None
    required_names: set[str] | None = None
    command_text_only: bool = False
    tool_call_id: str | None = None
    execution_context: dict[str, Any] | None = None
    canonicalized_from: str | None = None


@dataclass(slots=True)
class ToolDispatchResult:
    result: dict[str, Any]
    arguments: dict[str, Any]
    executed: bool
    execution_id: str | None = None


async def dispatch_tool(
    request: ToolDispatchRequest,
    *,
    validate: Validator,
    execute: Executor,
) -> ToolDispatchResult:
    """Applique les blocages avant de déléguer à l'exécuteur idempotent."""
    arguments = dict(request.arguments)
    seen = request.seen_read_signatures or set()
    explicit = request.explicit_names or set()
    required = request.required_names or set()

    if request.read_signature and request.read_signature in seen:
        return ToolDispatchResult(
            {
                "success": False,
                "duplicate_poll_blocked": True,
                "message": (
                    "Statut Code Workspace déjà lu pendant ce tour. N'interroge pas "
                    "la mission en boucle : réponds avec le dernier état observé. "
                    "Le superviseur Auto continue en arrière-plan."
                ),
            },
            arguments,
            False,
        )

    if explicit and request.name not in (explicit | required):
        requested = ", ".join(sorted(explicit))
        return ToolDispatchResult(
            {
                "error": (
                    f"⛔ Outil bloqué : tu as explicitement demandé {requested}. "
                    f"Marvin ne peut pas appeler '{request.name}' à la place ce tour-ci."
                ),
                "blocked_by_explicit_tool": True,
                "requested_tools": sorted(explicit),
            },
            arguments,
            False,
        )

    if request.command_text_only and request.name in EXECUTION_TOOLS:
        return ToolDispatchResult(
            {
                "error": (
                    "⛔ L'utilisateur a demandé LE TEXTE de la commande, pas son exécution "
                    f"— '{request.name}' est bloqué ce tour-ci. Réponds directement avec la "
                    "commande en texte (bloc de code), sans l'exécuter. Si l'utilisateur "
                    "veut vraiment l'exécuter, il te le dira explicitement (« lance-la », "
                    "« exécute »)."
                ),
                "blocked_command_text_only": True,
            },
            arguments,
            False,
        )

    missing_message = validate(request.name, arguments)
    if missing_message:
        return ToolDispatchResult(
            {"error": missing_message, "validation_failed": True},
            arguments,
            False,
        )

    if (
        request.permission_level == PERMISSION_SECURE
        and request.name in SECURE_BLOCKED_TOOLS
    ):
        return ToolDispatchResult(
            {
                "error": (
                    f"🛡️ Permission refusée (niveau Sécurisé) : "
                    f"l'outil '{request.name}' n'est pas autorisé. "
                    "Passez en mode Standard ou Expert dans les Paramètres "
                    "pour débloquer cette action."
                )
            },
            arguments,
            False,
        )

    if request.name in ALWAYS_CONFIRM_TOOLS:
        # Le LLM et le texte utilisateur appartiennent au même canal non fiable :
        # ils peuvent demander une action, mais pas fabriquer la preuve de clic UI.
        # Le gateway décide si l'autonomie active fournit une preuve valide ou
        # si le frontend doit afficher une approbation.
        arguments.pop("confirmed", None)
        arguments.pop("__confirmed", None)

    if request.tool_call_id or request.execution_context:
        outcome = await execute(
            request.name,
            arguments,
            request.conversation_id,
            request.request_id,
            tool_call_id=request.tool_call_id,
            execution_context=request.execution_context,
            canonicalized_from=request.canonicalized_from,
        )
    else:
        outcome = await execute(
            request.name,
            arguments,
            request.conversation_id,
            request.request_id,
        )
    if isinstance(outcome, dict):
        return ToolDispatchResult(outcome, arguments, True)
    return ToolDispatchResult(
        outcome.result,
        arguments,
        True,
        execution_id=getattr(outcome, "execution_id", None),
    )
