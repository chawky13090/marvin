"""Gateway commun des outils pour le chat, l'interface et MCP."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence

from agent_safety import validator_for
from agent_execution import execute_registered_tool
from config import (
    DANGEROUS_TOOLS,
    PERMISSION_EXPERT,
    PERMISSION_SECURE,
    SECURE_BLOCKED_TOOLS,
)

Executor = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolGatewayRequest:
    tool_name: str
    arguments: dict[str, Any]
    source: str
    permission_level: int
    conversation_id: str | None = None
    request_id: str | None = None
    confirmed_by_ui: bool = False


@dataclass(frozen=True, slots=True)
class ToolGatewayResult:
    result: Any
    executed: bool
    status_code: int = 200


def coverage_report(
    registry: Mapping[str, Executor],
    specifications: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    spec_names = {
        str(item.get("function", {}).get("name"))
        for item in specifications
        if item.get("function", {}).get("name")
    }
    registry_names = set(registry)
    covered = registry_names & spec_names
    return {
        "covered": len(covered),
        "total": len(registry_names),
        "complete": registry_names == spec_names,
        "missing_schema": sorted(registry_names - spec_names),
        "missing_executor": sorted(spec_names - registry_names),
        "restricted": len((DANGEROUS_TOOLS | SECURE_BLOCKED_TOOLS) & registry_names),
        "layers": [
            "schema_validation",
            "permission_policy",
            "confirmation_policy",
            "idempotency_receipt",
            "exception_capture",
            "result_contract",
            "execution_log",
            "audit_log",
        ],
    }


def _permission_denied(tool_name: str) -> dict[str, Any]:
    return {
        "error": (
            f"Permission refusée (niveau Sécurisé) : l'outil '{tool_name}' "
            "n'est pas autorisé. Passez en mode Standard ou Expert pour cette action."
        ),
        "permission_denied": True,
    }


async def execute_tool(
    request: ToolGatewayRequest,
    *,
    registry: Mapping[str, Executor],
    specifications: Sequence[dict[str, Any]],
    database: Any,
    normalizer: Callable[..., Any],
    audit_logger: Callable[..., Any],
) -> ToolGatewayResult:
    """Valide et exécute un outil avec le même contrat sur toutes les surfaces."""
    if request.tool_name not in registry:
        return ToolGatewayResult(
            {"error": f"Outil « {request.tool_name} » introuvable."},
            False,
            404,
        )
    arguments = dict(request.arguments)
    validation_error = validator_for(specifications)(request.tool_name, arguments)
    if validation_error:
        return ToolGatewayResult(
            {"error": validation_error, "validation_failed": True},
            False,
            422,
        )
    if (
        request.permission_level == PERMISSION_SECURE
        and request.tool_name in SECURE_BLOCKED_TOOLS
    ):
        return ToolGatewayResult(_permission_denied(request.tool_name), False, 403)
    if (
        request.confirmed_by_ui
        and request.tool_name in DANGEROUS_TOOLS
    ) or request.permission_level == PERMISSION_EXPERT:
        arguments["confirmed"] = True

    started = time.monotonic()
    result = await execute_registered_tool(
        request.tool_name,
        arguments,
        request.conversation_id or f"{request.source}:direct",
        request.request_id,
        registry=registry,
    )
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    try:
        result = normalizer(request.tool_name, result, duration_ms=duration_ms)
    except Exception:
        pass
    try:
        database.log_execution(
            request.tool_name,
            request.arguments,
            result,
            duration_ms,
        )
    except Exception:
        pass
    try:
        audit_logger(
            request.tool_name,
            request.arguments,
            result,
            source=request.source,
        )
    except Exception:
        pass
    return ToolGatewayResult(result, True)
