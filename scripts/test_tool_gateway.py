"""Contrats du gateway commun chat, UI et MCP."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
import tool_gateway
from config import PERMISSION_EXPERT, PERMISSION_SECURE, PERMISSION_STANDARD


class Database:
    logs: list[tuple] = []

    @classmethod
    def log_execution(cls, *values):
        cls.logs.append(values)


def normalize(name, result, *, duration_ms):
    return {**result, "normalized": True, "duration_ms": duration_ms}


AUDIT: list[tuple] = []


def audit(name, arguments, result, *, source):
    AUDIT.append((name, arguments, result, source))


async def main() -> None:
    calls: list[dict] = []

    async def calculator(arguments):
        calls.append(arguments)
        return {"success": True, "value": 2}

    async def file_delete(arguments):
        calls.append(arguments)
        return {
            "success": bool(arguments.get("confirmed")),
            "requiresConfirmation": not arguments.get("confirmed"),
        }

    async def broken(arguments):
        raise RuntimeError("panne simulée")

    registry = {
        "calculator": calculator,
        "file_delete": file_delete,
        "broken": broken,
    }
    specifications = [
        {
            "function": {
                "name": "calculator",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                },
            }
        },
        {
            "function": {
                "name": "file_delete",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "confirmed": {"type": "boolean"},
                    },
                    "required": ["path"],
                },
            }
        },
        {
            "function": {
                "name": "broken",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            }
        },
    ]

    invalid = await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            "calculator", {"expression": 2}, "ui", PERMISSION_STANDARD
        ),
        registry=registry,
        specifications=specifications,
        database=Database,
        normalizer=normalize,
        audit_logger=audit,
    )
    assert invalid.status_code == 422 and not invalid.executed and not calls

    secure = await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            "file_delete", {"path": "x"}, "ui", PERMISSION_SECURE
        ),
        registry=registry,
        specifications=specifications,
        database=Database,
        normalizer=normalize,
        audit_logger=audit,
    )
    assert secure.status_code == 403 and not secure.executed

    ui = await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            "file_delete",
            {"path": "x"},
            "ui",
            PERMISSION_STANDARD,
            confirmed_by_ui=True,
        ),
        registry=registry,
        specifications=specifications,
        database=Database,
        normalizer=normalize,
        audit_logger=audit,
    )
    assert ui.result["success"] and calls[-1]["confirmed"] is True

    mcp = await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            "file_delete", {"path": "x"}, "mcp", PERMISSION_STANDARD
        ),
        registry=registry,
        specifications=specifications,
        database=Database,
        normalizer=normalize,
        audit_logger=audit,
    )
    assert mcp.result["requiresConfirmation"] and "confirmed" not in calls[-1]

    expert = await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            "file_delete", {"path": "x"}, "mcp", PERMISSION_EXPERT
        ),
        registry=registry,
        specifications=specifications,
        database=Database,
        normalizer=normalize,
        audit_logger=audit,
    )
    assert expert.result["success"] and calls[-1]["confirmed"] is True

    failure = await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest("broken", {}, "mcp", PERMISSION_STANDARD),
        registry=registry,
        specifications=specifications,
        database=Database,
        normalizer=normalize,
        audit_logger=audit,
    )
    assert "panne simulée" in failure.result["error"]
    assert failure.result["normalized"] is True
    assert Database.logs and AUDIT[-1][3] == "mcp"

    report = tool_gateway.coverage_report(tools.TOOLS_REGISTRY, tools.TOOLS_SPEC)
    assert report["complete"] is True
    assert report["covered"] == report["total"] == 344
    assert report["missing_schema"] == report["missing_executor"] == []
    assert len(report["layers"]) == 8


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - gateway outils 344/344")
