"""Boucle agentique LLM native, indépendante du fournisseur de modèle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Mapping

from capability_catalog import CapabilityCatalog
from policy_engine import (
    ApprovalEvidence,
    CapabilityManifest,
    ExecutionEnvironment,
    PolicyAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
)


class DecisionKind(StrEnum):
    DISCOVER_TOOLS = "discover_tools"
    TOOL_CALL = "tool_call"
    FINAL_ANSWER = "final_answer"


class RunStatus(StrEnum):
    RUNNING = "running"
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AgentDecision:
    kind: DecisionKind
    query: str = ""
    tool_name: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    answer: str = ""


@dataclass(slots=True)
class NativeAgentState:
    run_id: str
    objective: str
    conversation_id: str = ""
    request_id: str = ""
    step_count: int = 0
    max_steps: int = 24
    status: RunStatus = RunStatus.RUNNING
    loaded_tools: list[str] = field(default_factory=lambda: ["tool_search"])
    observations: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    checkpoint_version: int = 0

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(frozen=True, slots=True)
class NativeRunResult:
    status: RunStatus
    state: NativeAgentState
    policy_decision: PolicyDecision | None = None


DecisionProvider = Callable[[NativeAgentState, list[dict[str, Any]]], Awaitable[AgentDecision]]
ToolExecutor = Callable[[str, dict[str, Any], NativeAgentState], Awaitable[dict[str, Any]]]
ManifestProvider = Callable[[str, Mapping[str, Any]], CapabilityManifest | None]
Verifier = Callable[[NativeAgentState, str], Awaitable[tuple[bool, list[str]]]]
CheckpointWriter = Callable[[NativeAgentState], Awaitable[None]]


class NativeAgentLoop:
    def __init__(
        self,
        *,
        catalog: CapabilityCatalog,
        policy_engine: PolicyEngine,
        manifest_provider: ManifestProvider,
        decide: DecisionProvider,
        execute: ToolExecutor,
        verify: Verifier,
        checkpoint: CheckpointWriter,
    ) -> None:
        self._catalog = catalog
        self._policy_engine = policy_engine
        self._manifest_provider = manifest_provider
        self._decide = decide
        self._execute = execute
        self._verify = verify
        self._checkpoint = checkpoint

    async def run(
        self,
        state: NativeAgentState,
        *,
        identity: str,
        permission_level: int,
        environment: ExecutionEnvironment,
        source: str = "llm_native",
        approval: ApprovalEvidence | None = None,
    ) -> NativeRunResult:
        while state.step_count < state.max_steps:
            state.status = RunStatus.RUNNING
            visible_specs = self._catalog.exact_specifications(state.loaded_tools)
            decision = await self._decide(state, visible_specs)
            state.step_count += 1

            if decision.kind is DecisionKind.DISCOVER_TOOLS:
                try:
                    discovery = self._catalog.search(decision.query, limit=12)
                except ValueError as exc:
                    discovery = {
                        "status": "failed",
                        "category": "invalid_discovery_query",
                        "retryable": True,
                        "message": str(exc),
                    }
                candidates = [
                    str(item.get("name") or "")
                    for item in discovery.get("candidates", [])
                    if isinstance(item, dict) and item.get("name")
                ]
                for name in candidates:
                    if name not in state.loaded_tools:
                        state.loaded_tools.append(name)
                state.observations.append({
                    "type": "tool_discovery",
                    "result": discovery,
                })
                await self._checkpoint(state)
                continue

            if decision.kind is DecisionKind.TOOL_CALL:
                if decision.tool_name not in state.loaded_tools:
                    state.observations.append({
                        "type": "tool_result",
                        "tool": decision.tool_name,
                        "status": "failed",
                        "category": "tool_not_loaded",
                        "retryable": True,
                    })
                    await self._checkpoint(state)
                    continue
                manifest = self._manifest_provider(
                    decision.tool_name,
                    decision.arguments,
                )
                context = PolicyContext(
                    identity=identity,
                    tool_name=decision.tool_name,
                    arguments=decision.arguments,
                    permission_level=permission_level,
                    environment=environment,
                    source=source,
                    target=str(decision.arguments.get("target") or ""),
                    approval=approval,
                    request_id=state.request_id,
                    conversation_id=state.conversation_id,
                )
                policy = self._policy_engine.evaluate(manifest, context)
                if policy.action is PolicyAction.REQUIRE_APPROVAL:
                    state.status = RunStatus.PENDING_APPROVAL
                    state.observations.append({
                        "type": "approval_required",
                        "tool": decision.tool_name,
                        "call_digest": policy.call_digest,
                        "risk_tier": int(policy.risk_tier),
                        "constraints": dict(policy.constraints),
                    })
                    await self._checkpoint(state)
                    return NativeRunResult(state.status, state, policy)
                if policy.action is PolicyAction.DENY:
                    state.observations.append({
                        "type": "tool_result",
                        "tool": decision.tool_name,
                        "status": "denied",
                        "category": policy.reason_code,
                        "retryable": True,
                    })
                    await self._checkpoint(state)
                    continue
                result = await self._execute(
                    decision.tool_name,
                    dict(decision.arguments),
                    state,
                )
                state.observations.append({
                    "type": "tool_result",
                    "tool": decision.tool_name,
                    "result": result,
                })
                await self._checkpoint(state)
                continue

            if decision.kind is DecisionKind.FINAL_ANSWER:
                satisfied, gaps = await self._verify(state, decision.answer)
                if satisfied:
                    state.final_answer = decision.answer
                    state.status = RunStatus.COMPLETED
                    await self._checkpoint(state)
                    return NativeRunResult(state.status, state)
                state.observations.append({
                    "type": "contract_verification",
                    "status": "incomplete",
                    "gaps": [str(gap)[:500] for gap in gaps[:20]],
                })
                await self._checkpoint(state)
                continue

            state.observations.append({
                "type": "runtime_error",
                "category": "unsupported_decision",
            })
            await self._checkpoint(state)

        state.status = RunStatus.STOPPED
        state.observations.append({
            "type": "run_stopped",
            "category": "maximum_steps_reached",
        })
        await self._checkpoint(state)
        return NativeRunResult(state.status, state)

