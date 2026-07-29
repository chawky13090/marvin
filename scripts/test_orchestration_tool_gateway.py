"""Contrats du harness pour multi-agents et workflows persistants."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import multi_agents, workflows


async def _check_multi_agents() -> None:
    calls = []

    async def execute(name, arguments, **options):
        calls.append((name, arguments, options))
        if name == "missing":
            return SimpleNamespace(
                result={"error": "Outil inconnu : missing"},
                executed=False,
            )
        return SimpleNamespace(result={"success": True}, executed=True)

    with patch.object(multi_agents.tool_runtime, "execute", side_effect=execute):
        success = await multi_agents._run_one(
            multi_agents.AgentTask(id="task-1", tool_name="calculator")
        )
        missing = await multi_agents._run_one(
            multi_agents.AgentTask(id="task-2", tool_name="missing")
        )
    assert success["success"] is True
    assert missing["success"] is False
    assert calls[0][2]["source"] == "multi_agent"
    assert calls[0][2]["conversation_id"] == "multi-agent:task-1"

    try:
        multi_agents.AgentRunRequest(
            tasks=[
                multi_agents.AgentTask(id=f"task-{index}", tool_name="calculator")
                for index in range(33)
            ]
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Le parallélisme doit être borné à 32 tâches.")


async def _check_workflow() -> None:
    attempts = []

    async def execute(name, arguments, **options):
        attempts.append((name, arguments, options))
        if len(attempts) == 1:
            return SimpleNamespace(result={"error": "transitoire"}, executed=True)
        return SimpleNamespace(result={"success": True, "value": 2}, executed=True)

    workflow = {
        "id": "workflow-1",
        "steps": [
            {
                "id": "step-1",
                "tool_name": "calculator",
                "args": {"expression": "1+1"},
                "retries": 20,
                "enabled": True,
            }
        ],
    }
    finish = Mock()
    update = Mock()
    with (
        patch.object(workflows.db, "get_workflow", return_value=workflow),
        patch.object(workflows.db, "create_workflow_run", return_value={"id": "run-1"}),
        patch.object(workflows.db, "finish_workflow_run", finish),
        patch.object(workflows.db, "update_workflow", update),
        patch.object(workflows.asyncio, "sleep", return_value=None),
        patch.object(workflows.tool_runtime, "execute", side_effect=execute),
    ):
        result = await workflows.run_workflow("workflow-1")

    assert result["status"] == "success"
    assert result["steps_results"][0]["attempts"] == 2
    assert attempts[0][2] == {
        "source": "workflow",
        "conversation_id": "workflow:run-1",
        "request_id": "workflow:run-1:step-1:1",
    }
    assert attempts[1][2]["request_id"] == "workflow:run-1:step-1:2"
    finish.assert_called_once()
    update.assert_called_once()

    try:
        workflows.WorkflowStep(id="bad id", tool_name="calculator", retries=4)
    except ValidationError:
        pass
    else:
        raise AssertionError("Les identités et retries de workflow doivent être bornés.")


def main() -> int:
    asyncio.run(_check_multi_agents())
    asyncio.run(_check_workflow())
    print("Orchestration Gateway OK - multi-agents bornés, retries et corrélation workflow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
