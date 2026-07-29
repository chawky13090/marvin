"""Contrats de composition du runtime commun des outils."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api_observability
import tool_gateway
import tool_runtime
from config import DEFAULT_PERMISSION_LEVEL, PERMISSION_STANDARD


class Storage:
    @staticmethod
    def get_setting(_name):
        return PERMISSION_STANDARD


class BrokenStorage:
    @staticmethod
    def get_setting(_name):
        raise OSError("indisponible")


async def main() -> None:
    captured = []

    async def fake_execute(request, **dependencies):
        captured.append((request, dependencies))
        return tool_gateway.ToolGatewayResult({"success": True}, True)

    original = tool_runtime.tool_gateway.execute_tool
    token = api_observability._current_request_id.set("runtime-request-123")
    tool_runtime.tool_gateway.execute_tool = fake_execute
    try:
        result = await tool_runtime.execute(
            "calculator",
            {"expression": "1+1"},
            source="calendar_ui",
            database=Storage,
            registry={},
            specifications=[],
            normalizer=lambda *_args, **_kwargs: None,
            audit_logger=lambda *_args, **_kwargs: None,
        )
        assert result.executed
        request, dependencies = captured[-1]
        assert request.permission_level == PERMISSION_STANDARD
        assert request.request_id == "runtime-request-123"
        assert request.source == "calendar_ui"
        assert dependencies["database"] is Storage

        await tool_runtime.execute(
            "calculator",
            {},
            source="x" * 200,
            permission_level=999,
            registry={},
            specifications=[],
            database=Storage,
            normalizer=lambda *_args, **_kwargs: None,
            audit_logger=lambda *_args, **_kwargs: None,
        )
        assert captured[-1][0].permission_level == DEFAULT_PERMISSION_LEVEL
        assert len(captured[-1][0].source) == 80

        await tool_runtime.execute(
            "calculator",
            {},
            source=" ",
            permission_level="invalid",
            registry={},
            specifications=[],
            database=Storage,
            normalizer=lambda *_args, **_kwargs: None,
            audit_logger=lambda *_args, **_kwargs: None,
        )
        assert captured[-1][0].permission_level == DEFAULT_PERMISSION_LEVEL
        assert captured[-1][0].source == "unknown"
    finally:
        tool_runtime.tool_gateway.execute_tool = original
        api_observability._current_request_id.reset(token)

    assert tool_runtime.current_permission_level(BrokenStorage) == DEFAULT_PERMISSION_LEVEL
    print("Tool Runtime OK - permission fail-closed, corrélation et injection bornée.")


if __name__ == "__main__":
    asyncio.run(main())
