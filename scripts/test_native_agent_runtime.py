"""Scénarios complets de la boucle agentique native sans effets réels."""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from capability_catalog import CapabilityCatalog  # noqa: E402
from native_agent_runtime import (  # noqa: E402
    AgentDecision,
    DecisionKind,
    NativeAgentLoop,
    NativeAgentState,
    RunStatus,
)
from policy_engine import (  # noqa: E402
    CapabilityManifest,
    DataClass,
    Effect,
    ExecutionEnvironment,
    PolicyEngine,
    Reversibility,
    Scope,
)
from repositories.agent_runs import AgentRunConflict, AgentRunRepository  # noqa: E402


SPECS = [
    {
        "type": "function",
        "function": {
            "name": "tool_search",
            "description": "Découvre les outils disponibles",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_read_logs",
            "description": "Lit les journaux d'un conteneur Docker",
            "parameters": {
                "type": "object",
                "properties": {"container": {"type": "string"}},
                "required": ["container"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_send",
            "description": "Envoie un courriel",
            "parameters": {
                "type": "object",
                "properties": {"to": {"type": "string"}},
                "required": ["to"],
                "additionalProperties": False,
            },
        },
    },
]


def manifest_provider(name, _arguments):
    if name == "docker_read_logs":
        return CapabilityManifest(
            name=name,
            effects=frozenset({Effect.PUBLIC_READ}),
            scopes=frozenset({Scope.HOST}),
            data_classes=frozenset({DataClass.PUBLIC}),
            reversibility=Reversibility.NOT_APPLICABLE,
            idempotent=True,
            verified=True,
        )
    if name == "email_send":
        return CapabilityManifest(
            name=name,
            effects=frozenset({Effect.EXTERNAL_COMMUNICATION}),
            scopes=frozenset({Scope.EXTERNAL_ACCOUNT}),
            data_classes=frozenset({DataClass.PERSONAL}),
            reversibility=Reversibility.NONE,
            verified=True,
        )
    return None


async def successful_run() -> None:
    decisions = iter([
        AgentDecision(DecisionKind.DISCOVER_TOOLS, query="lire logs docker"),
        AgentDecision(
            DecisionKind.TOOL_CALL,
            tool_name="docker_read_logs",
            arguments={"container": "gitea"},
        ),
        AgentDecision(DecisionKind.FINAL_ANSWER, answer="Gitea est sain."),
    ])
    executed: list[str] = []
    checkpoints: list[dict] = []

    async def decide(_state, _specs):
        return next(decisions)

    async def execute(name, _arguments, _state):
        executed.append(name)
        return {"status": "ok", "lines": ["ready"]}

    async def verify(_state, answer):
        return (bool(answer and executed), [])

    async def checkpoint(state):
        checkpoints.append(state.public_dict())

    loop = NativeAgentLoop(
        catalog=CapabilityCatalog(SPECS),
        policy_engine=PolicyEngine(),
        manifest_provider=manifest_provider,
        decide=decide,
        execute=execute,
        verify=verify,
        checkpoint=checkpoint,
    )
    result = await loop.run(
        NativeAgentState("run-success", "Diagnostique Gitea"),
        identity="user:test",
        permission_level=1,
        environment=ExecutionEnvironment.HOST,
    )
    assert result.status is RunStatus.COMPLETED
    assert executed == ["docker_read_logs"]
    assert "docker_read_logs" in result.state.loaded_tools
    assert len(checkpoints) == 3


async def approval_run() -> None:
    decisions = iter([
        AgentDecision(DecisionKind.DISCOVER_TOOLS, query="envoyer courriel"),
        AgentDecision(
            DecisionKind.TOOL_CALL,
            tool_name="email_send",
            arguments={"to": "test@example.invalid"},
        ),
    ])
    executed: list[str] = []

    async def decide(_state, _specs):
        return next(decisions)

    async def execute(name, _arguments, _state):
        executed.append(name)
        return {"status": "sent"}

    async def verify(_state, _answer):
        return True, []

    async def checkpoint(_state):
        return None

    loop = NativeAgentLoop(
        catalog=CapabilityCatalog(SPECS),
        policy_engine=PolicyEngine(),
        manifest_provider=manifest_provider,
        decide=decide,
        execute=execute,
        verify=verify,
        checkpoint=checkpoint,
    )
    result = await loop.run(
        NativeAgentState("run-approval", "Envoie le courriel"),
        identity="user:test",
        permission_level=2,
        environment=ExecutionEnvironment.HOST,
    )
    assert result.status is RunStatus.PENDING_APPROVAL
    assert executed == []
    assert result.policy_decision is not None


def repository_test() -> None:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "agent-runs.db"

        @contextmanager
        def scope():
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

        repository = AgentRunRepository(scope)
        repository.ensure_schema()
        version = repository.create(
            "run-1",
            conversation_id="conv-1",
            request_id="req-1",
            status="running",
            state={"step": 0},
        )
        assert version == 1
        version = repository.save(
            "run-1",
            expected_version=1,
            status="pending_approval",
            state={"step": 1},
        )
        assert version == 2
        assert repository.load("run-1")["state"] == {"step": 1}
        try:
            repository.save(
                "run-1",
                expected_version=1,
                status="failed",
                state={"step": 99},
            )
        except AgentRunConflict:
            pass
        else:
            raise AssertionError("Une écriture concurrente obsolète doit être refusée.")
        assert repository.load("run-1")["state"] == {"step": 1}
        assert repository.delete("run-1") is True


def main() -> None:
    asyncio.run(successful_run())
    asyncio.run(approval_run())
    repository_test()
    print("OK - boucle Discover/Decide/Authorize/Execute/Verify et checkpoints atomiques")


if __name__ == "__main__":
    main()
