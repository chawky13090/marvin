"""Contrats des routes chat, outils et MCP extraites de main.py."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import agent_gateway


async def _collect_stream(response) -> str:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
    return b"".join(chunks).decode("utf-8")


async def _exercise_routes() -> None:
    async def generated():
        yield 'data: {"type":"done"}\n\n'

    with patch.object(agent_gateway, "run_agent", return_value=generated()):
        response = await agent_gateway.chat(
            agent_gateway.ChatRequest(messages=[{"role": "user", "content": "bonjour"}])
        )
        body = await _collect_stream(response)
    assert '"type":"done"' in body
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    async def rejected_subscription(**_kwargs):
        raise ValueError("secret interne qui ne doit pas sortir")
        yield ""

    with patch.object(
        agent_gateway.chat_turn_runtime,
        "subscribe",
        rejected_subscription,
    ):
        response = await agent_gateway.chat(
            agent_gateway.ChatRequest(
                messages=[{"role": "user", "content": "bonjour"}],
                requestId="request-1",
            )
        )
        body = await _collect_stream(response)
    assert "secret interne" not in body
    assert "autre demande" in body

    outcome = SimpleNamespace(status_code=200, result={"success": True})
    with patch.object(
        agent_gateway,
        "_execute_through_gateway",
        AsyncMock(return_value=outcome),
    ) as execute:
        response = await agent_gateway.execute_tool_endpoint(
            agent_gateway.ToolExecuteRequest(toolName="date_now")
        )
    assert response == {"result": {"success": True}}
    assert execute.await_args.kwargs == {
        "source": "ui",
        "confirmed_by_ui": True,
    }


def _expect_invalid(factory) -> None:
    try:
        factory()
    except ValidationError:
        return
    raise AssertionError("La charge invalide aurait dû être refusée.")


def main() -> int:
    _expect_invalid(lambda: agent_gateway.ChatRequest(messages=[]))
    _expect_invalid(
        lambda: agent_gateway.ChatRequest(
            messages=[{"role": "user", "content": "x"}],
            conversationId="../escape",
        )
    )
    _expect_invalid(
        lambda: agent_gateway.ToolExecuteRequest(toolName="../powershell", args={})
    )
    with patch.object(agent_gateway, "MAX_CHAT_PAYLOAD_BYTES", 100):
        _expect_invalid(
            lambda: agent_gateway.ChatRequest(
                messages=[{"role": "user", "content": "x" * 200}]
            )
        )
    with (
        patch.object(agent_gateway.db, "get_setting", return_value=99),
    ):
        assert (
            agent_gateway._current_permission_level()
            == agent_gateway.DEFAULT_PERMISSION_LEVEL
        )
    with patch.object(
        agent_gateway.db,
        "get_setting",
        side_effect=RuntimeError("base indisponible"),
    ):
        assert (
            agent_gateway._current_permission_level()
            == agent_gateway.DEFAULT_PERMISSION_LEVEL
        )

    config = asyncio.run(agent_gateway.mcp_config())
    parsed = json.loads(config["config_json"])
    assert parsed["mcpServers"]["marvin"]["command"] == sys.executable
    assert Path(config["server_script"]).name == "mcp_server.py"
    assert "C:\\Users\\Chawb" not in config["config_json"]

    asyncio.run(_exercise_routes())

    main_source = (BACKEND / "main.py").read_text(encoding="utf-8-sig")
    assert "app.include_router(agent_gateway_router)" in main_source
    assert "class ChatRequest" not in main_source
    assert "class ToolExecuteRequest" not in main_source
    assert 'content={"detail": f"Erreur interne : {exc}"}' not in main_source
    assert '"incident_id": incident_id' in main_source

    routes = {
        route.path
        for route in agent_gateway.router.routes
    }
    assert routes == {
        "/api/chat",
        "/api/tools",
        "/api/tools/list",
        "/api/mcp/execute",
        "/api/mcp/config",
    }
    print("Agent Gateway API OK - extraction, bornes, SSE, outils, MCP et erreurs expurgées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
