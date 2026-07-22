"""Regressions de la frontiere entre le LLM et les outils reels."""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_execution as execution


async def _exercise_execution() -> None:
    received: list[dict] = []

    async def executor(arguments: dict) -> dict:
        received.append(arguments)
        return {"success": True, "value": arguments["value"]}

    async def replay(**kwargs):
        assert kwargs["request_id"] == "request-1"
        assert kwargs["conversation_id"] == "conversation-1"
        assert kwargs["tool_name"] == "sample_tool"
        return await kwargs["operation"]()

    with patch.object(execution, "execute_once", side_effect=replay) as execute_once:
        result = await execution.execute_registered_tool(
            "sample_tool",
            {"value": 7},
            "conversation-1",
            "request-1",
            registry={"sample_tool": executor},
        )
    assert result == {"success": True, "value": 7}
    assert received == [{"value": 7}]
    assert execute_once.await_count == 1

    unknown = await execution.execute_registered_tool(
        "missing", {}, "conversation-1", None, registry={}
    )
    assert unknown == {"error": "Outil inconnu : missing"}

    failing = AsyncMock(side_effect=RuntimeError("panne controlee"))
    with (
        patch.object(execution, "execute_once", side_effect=replay),
        patch.object(execution, "log_tool_exception", return_value={"error": "panne controlee"}),
    ):
        failed = await execution.execute_registered_tool(
            "sample_tool",
            {},
            "conversation-1",
            "request-1",
            registry={"sample_tool": failing},
        )
    assert failed == {"error": "panne controlee"}


def main() -> int:
    allowed = {"net_ping", "pc_process_kill"}
    content = (
        '```json\n{"name":"net-ping","arguments":{"host":"127.0.0.1"}}\n```\n'
        'pc_process_kill({"pid": 42})\n'
        '{"name":"email_send","arguments":{"to":"outside@example.test"}}'
    )
    calls = execution.salvage_text_tool_calls(content, allowed)
    assert calls == [
        {"function": {"name": "net_ping", "arguments": {"host": "127.0.0.1"}}},
        {"function": {"name": "pc_process_kill", "arguments": {"pid": 42}}},
    ]

    assert execution.is_tooling_failure({"error": "outil inconnu"}) is True
    assert execution.is_tooling_failure({"error": "Accès refusé par l'administrateur"}) is False
    assert execution.is_tooling_failure({"success": False, "stderr": "ParserError: unexpected token"}) is True
    assert execution.is_tooling_failure({"success": False, "stderr": "host unreachable"}) is False

    asyncio.run(_exercise_execution())

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not {
        "_execute_registered_tool",
        "_log_tool_exception",
        "_is_tooling_failure",
        "_salvage_text_tool_calls",
    } & definitions

    import agent

    assert callable(agent._execute_registered_tool)
    assert callable(agent._log_tool_exception)
    assert callable(agent._is_tooling_failure)
    assert callable(agent._salvage_text_tool_calls)
    print("Agent Execution OK - registre, recus, erreurs, salvage et facade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
