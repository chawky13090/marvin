"""Contrats d'expurgation et d'observabilité du pont MCP Marvin."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import mcp_server


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "result": {"success": True},
            "observability": {
                "status": "degraded",
                "errors": ["audit:OSError"],
            },
        }


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        return _Response()


async def _exercise() -> None:
    with patch.object(
        mcp_server,
        "_fetch_tools",
        AsyncMock(side_effect=RuntimeError("secret-interne token=abc")),
    ):
        unavailable = await mcp_server.handle_list_tools()
    description = unavailable[0].description
    assert "secret-interne" not in description
    assert "Incident :" in description

    with patch.object(mcp_server.httpx, "AsyncClient", return_value=_Client()):
        response = await mcp_server.handle_call_tool("date_now", {})
    payload = json.loads(response[0].text)
    assert payload["_observability"]["errors"] == ["audit:OSError"]

    with patch.object(
        mcp_server.httpx,
        "AsyncClient",
        side_effect=RuntimeError("C:\\chemin\\prive token=abc"),
    ):
        failed = await mcp_server.handle_call_tool("date_now", {})
    assert "chemin" not in failed[0].text
    assert "token" not in failed[0].text
    assert "Incident :" in failed[0].text


def main() -> int:
    asyncio.run(_exercise())
    print("MCP Server Boundary OK - erreurs expurgées et observabilité propagée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
