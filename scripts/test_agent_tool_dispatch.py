"""Régressions de la politique de dispatch des outils."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_tool_dispatch import ALWAYS_CONFIRM_TOOLS, ToolDispatchRequest, dispatch_tool
from config import DANGEROUS_TOOLS, PERMISSION_EXPERT, PERMISSION_SECURE


async def main() -> int:
    calls: list[tuple] = []

    async def execute(name, arguments, conversation_id, request_id):
        calls.append((name, arguments, conversation_id, request_id))
        return {"success": True}

    def valid(name, arguments):
        return None

    duplicate = await dispatch_tool(
        ToolDispatchRequest(
            "code_workspace_status", {"mission_id": "m1"}, "c1", "r1", 2,
            read_signature="status:m1",
            seen_read_signatures={"status:m1"},
        ),
        validate=valid,
        execute=execute,
    )
    assert duplicate.result["duplicate_poll_blocked"] and not duplicate.executed

    substituted = await dispatch_tool(
        ToolDispatchRequest(
            "net_ping", {}, "c1", "r1", 2, explicit_names={"file_find"}
        ),
        validate=valid,
        execute=execute,
    )
    assert substituted.result["blocked_by_explicit_tool"]

    text_only = await dispatch_tool(
        ToolDispatchRequest(
            "pc_run_powershell", {"script": "Get-Date"}, "c1", "r1", 2,
            command_text_only=True,
        ),
        validate=valid,
        execute=execute,
    )
    assert text_only.result["blocked_command_text_only"]

    invalid = await dispatch_tool(
        ToolDispatchRequest("calculator", {}, "c1", None, 2),
        validate=lambda *_: "expression requise",
        execute=execute,
    )
    assert invalid.result["validation_failed"]

    secure = await dispatch_tool(
        ToolDispatchRequest(
            "pc_run_powershell", {"script": "Get-Date"}, "c1", None,
            PERMISSION_SECURE,
        ),
        validate=valid,
        execute=execute,
    )
    assert "Permission refusée" in secure.result["error"]

    expert = await dispatch_tool(
        ToolDispatchRequest(
            "calculator", {"expression": "1+1"}, "c1", "r1",
            PERMISSION_EXPERT,
        ),
        validate=valid,
        execute=execute,
    )
    assert expert.executed and "confirmed" not in expert.arguments

    irreversible = await dispatch_tool(
        ToolDispatchRequest(
            "file_delete",
            {"path": "x", "confirmed": True},
            "c1",
            "r1",
            PERMISSION_EXPERT,
        ),
        validate=valid,
        execute=execute,
    )
    assert "confirmed" not in irreversible.arguments
    assert DANGEROUS_TOOLS <= set(ALWAYS_CONFIRM_TOOLS)
    assert len(calls) == 2
    print(
        "Agent Tool Dispatch OK - polling, explicite, texte, validation, permissions et confirmation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
