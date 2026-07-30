"""Gateway commun des outils pour le chat, l'interface et MCP."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence

import agent_autonomy
from agent_safety import validator_for
from agent_execution import execute_registered_tool
from critical_tool_policy import approval_summary, manifest_for_critical_call
from policy_engine import (
    ApprovalEvidence,
    ExecutionEnvironment,
    PolicyAction,
    PolicyContext,
    PolicyEngine,
    call_digest,
    risk_tier,
)
from repositories import tool_approvals
from config import (
    CONDITIONAL_TOOL_SAFE_ACTIONS,
    DANGEROUS_TOOLS,
    PERMISSION_EXPERT,
    PERMISSION_SECURE,
    SECURE_BLOCKED_TOOLS,
)

Executor = Callable[[dict[str, Any]], Awaitable[Any]]


def _conditional_mutation(tool_name: str, arguments: Mapping[str, Any]) -> bool:
    safe_actions = CONDITIONAL_TOOL_SAFE_ACTIONS.get(tool_name)
    if safe_actions is None:
        return False
    action = str(arguments.get("action") or "").strip().lower()
    return action not in safe_actions


@dataclass(frozen=True, slots=True)
class ToolGatewayRequest:
    tool_name: str
    arguments: dict[str, Any]
    source: str
    permission_level: int
    conversation_id: str | None = None
    request_id: str | None = None
    confirmed_by_ui: bool = False
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class ToolGatewayResult:
    result: Any
    executed: bool
    status_code: int = 200
    observation_errors: tuple[str, ...] = ()


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
        "restricted": len(
            (
                DANGEROUS_TOOLS
                | SECURE_BLOCKED_TOOLS
                | set(CONDITIONAL_TOOL_SAFE_ACTIONS)
            )
            & registry_names
        ),
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
    conditional_mutation = _conditional_mutation(request.tool_name, arguments)
    if (
        request.permission_level == PERMISSION_SECURE
        and (
            request.tool_name in SECURE_BLOCKED_TOOLS
            or conditional_mutation
        )
    ):
        return ToolGatewayResult(_permission_denied(request.tool_name), False, 403)
    dangerous_call = request.tool_name in DANGEROUS_TOOLS or conditional_mutation
    if dangerous_call:
        # Le digest porte sur les arguments métier, jamais sur un booléen fabriqué
        # par le modèle. La preuve UI est recréée pour ce digest exact seulement.
        arguments.pop("confirmed", None)
        arguments.pop("__confirmed", None)
        context = PolicyContext(
            identity=f"{request.source}:user",
            tool_name=request.tool_name,
            arguments=arguments,
            permission_level=request.permission_level,
            environment=ExecutionEnvironment.HOST,
            source=request.source,
            target=str(
                arguments.get("path")
                or arguments.get("host")
                or arguments.get("id")
                or ""
            )[:2_000],
            request_id=request.request_id or "",
            conversation_id=request.conversation_id or "",
        )
        digest = call_digest(context)
        if request.confirmed_by_ui:
            context = PolicyContext(
                identity=context.identity,
                tool_name=context.tool_name,
                arguments=context.arguments,
                permission_level=context.permission_level,
                environment=context.environment,
                source=context.source,
                target=context.target,
                approval=ApprovalEvidence(
                    call_digest=digest,
                    approved_by="trusted_ui",
                    expires_at=time.time() + 60,
                    approval_id=request.request_id or f"ui-{digest[:16]}",
                ),
                request_id=context.request_id,
                conversation_id=context.conversation_id,
            )
        manifest = manifest_for_critical_call(request.tool_name, arguments)
        tier = risk_tier(manifest, context.environment)
        try:
            autonomy = agent_autonomy.current(database)
        except Exception:
            autonomy = {"mode": "normal", "active": False}
        if autonomy.get("active") and agent_autonomy.allows(
            str(autonomy.get("mode") or "normal"),
            int(tier),
        ):
            context = PolicyContext(
                identity=context.identity,
                tool_name=context.tool_name,
                arguments=context.arguments,
                permission_level=context.permission_level,
                environment=context.environment,
                source=context.source,
                target=context.target,
                approval=ApprovalEvidence(
                    call_digest=digest,
                    approved_by=f"autonomy:{autonomy['mode']}",
                    expires_at=time.time() + 60,
                    approval_id=f"autonomy-{autonomy['mode']}-{digest[:16]}",
                ),
                request_id=context.request_id,
                conversation_id=context.conversation_id,
            )
        decision = PolicyEngine().evaluate(manifest, context)
        if decision.action is PolicyAction.DENY:
            return ToolGatewayResult(
                {
                    "error": "Action refusée par la politique d'effets.",
                    "policyReason": decision.reason_code,
                    "riskTier": int(decision.risk_tier),
                },
                False,
                403,
            )
        if decision.action is PolicyAction.REQUIRE_APPROVAL:
            approval = tool_approvals.create_or_reuse(
                call_digest=decision.call_digest,
                tool_name=request.tool_name,
                arguments=arguments,
                conversation_id=request.conversation_id or "",
                request_id=request.request_id or "",
                source=request.source,
                risk_tier=int(decision.risk_tier),
            )
            return ToolGatewayResult(
                {
                    "success": False,
                    "requiresConfirmation": True,
                    "approvalId": approval["id"],
                    "expiresAt": approval["expires_at"],
                    "message": (
                        f"Autoriser « {request.tool_name} » sur "
                        f"{approval_summary(request.tool_name, arguments)} ? "
                        "Utilisez les boutons du chat : une réponse texte ne valide pas l'action."
                    ),
                    "policyReason": decision.reason_code,
                    "approvalDigest": decision.call_digest,
                    "riskTier": int(decision.risk_tier),
                },
                False,
                409,
            )
        arguments["confirmed"] = True

    started = time.monotonic()
    result = await execute_registered_tool(
        request.tool_name,
        arguments,
        request.conversation_id or f"{request.source}:direct",
        request.request_id,
        registry=registry,
        client_idempotency_key=request.idempotency_key,
    )
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    observation_errors: list[str] = []
    try:
        result = normalizer(request.tool_name, result, duration_ms=duration_ms)
    except Exception as exc:
        observation_errors.append(f"normalizer:{type(exc).__name__}")
    try:
        database.log_execution(
            request.tool_name,
            request.arguments,
            result,
            duration_ms,
            conversation_id=request.conversation_id,
            request_id=request.request_id,
        )
    except Exception as exc:
        observation_errors.append(f"execution:{type(exc).__name__}")
    try:
        audit_logger(
            request.tool_name,
            request.arguments,
            result,
            source=request.source,
            request_id=request.request_id,
        )
    except Exception as exc:
        observation_errors.append(f"audit:{type(exc).__name__}")
    return ToolGatewayResult(
        result,
        True,
        observation_errors=tuple(observation_errors),
    )
