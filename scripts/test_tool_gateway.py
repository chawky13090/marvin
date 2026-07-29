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
    logs: list[tuple[tuple, dict]] = []

    @classmethod
    def log_execution(cls, *values, **options):
        cls.logs.append((values, options))


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
        raise RuntimeError("secret-interne token=abc")

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
            conversation_id="conversation-ui",
            confirmed_by_ui=True,
        ),
        registry=registry,
        specifications=specifications,
        database=Database,
        normalizer=normalize,
        audit_logger=audit,
    )
    assert ui.result["success"] and calls[-1]["confirmed"] is True
    assert Database.logs[-1][1]["conversation_id"] == "conversation-ui"

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

    forged_confirmation = await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            "file_delete",
            {"path": "x", "confirmed": True},
            "mcp",
            PERMISSION_STANDARD,
        ),
        registry=registry,
        specifications=specifications,
        database=Database,
        normalizer=normalize,
        audit_logger=audit,
    )
    assert forged_confirmation.result["requiresConfirmation"]
    assert "confirmed" not in calls[-1]

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
    assert "erreur interne" in failure.result["error"]
    assert "secret-interne" not in str(failure.result)
    assert failure.result["normalized"] is True
    assert Database.logs and AUDIT[-1][3] == "mcp"

    def broken_normalizer(*_args, **_kwargs):
        raise RuntimeError("normalisation indisponible")

    class BrokenDatabase:
        @staticmethod
        def log_execution(*_args, **_kwargs):
            raise OSError("base indisponible")

    def broken_audit(*_args, **_kwargs):
        raise OSError("audit indisponible")

    degraded = await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            "calculator", {"expression": "1+1"}, "ui", PERMISSION_STANDARD
        ),
        registry=registry,
        specifications=specifications,
        database=BrokenDatabase,
        normalizer=broken_normalizer,
        audit_logger=broken_audit,
    )
    assert degraded.executed is True
    assert degraded.result["success"] is True
    assert degraded.observation_errors == (
        "normalizer:RuntimeError",
        "execution:OSError",
        "audit:OSError",
    )

    report = tool_gateway.coverage_report(tools.TOOLS_REGISTRY, tools.TOOLS_SPEC)
    assert report["complete"] is True
    assert report["covered"] == report["total"] == 344
    assert report["missing_schema"] == report["missing_executor"] == []
    assert len(report["layers"]) == 8


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - gateway outils 344/344")
