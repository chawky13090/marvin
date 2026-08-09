"""Contrat de disponibilite reseau et de decouverte des outils Marvin."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_tool_selection as selection
import tool_availability as availability
import tools


def _names(specs: list[dict]) -> set[str]:
    return {str(item.get("function", {}).get("name") or "") for item in specs}


async def _route_empty(_text: str) -> dict:
    return {"semantic": set(), "learned": set()}


def main() -> int:
    names = _names(tools.TOOLS_SPEC)
    coverage = availability.validate_coverage(names)
    assert coverage == {
        "schema": availability.SCHEMA,
        "tool_count": 364,
        "inventory_count": 364,
        "missing": [],
        "orphaned": [],
        "valid": True,
    }, coverage

    inventory = availability.load_inventory()
    assert inventory["file_read"]["network"] == "local"
    assert inventory["web_search"] == {
        "network": "internet",
        "services": ["searxng"],
        "offline_capable": False,
    }
    assert inventory["net_ping"]["network"] == "target"
    assert inventory["net_subnet_calc"]["network"] == "local"
    assert inventory["net_whois"]["network"] == "internet"
    assert inventory["ssh_list"]["network"] == "local"
    assert inventory["ssh_exec"]["network"] == "target"
    assert inventory["email_accounts"]["network"] == "local"
    assert inventory["email_summarize"]["offline_capable"] is True

    offline = availability.ConnectivitySnapshot(
        internet=False,
        services={"ollama": True, "searxng": False},
        observed_at=10.0,
    )
    states = availability.availability_map(names, offline)
    assert states["file_read"]["status"] == "available"
    assert states["web_search"]["status"] == "unavailable"
    assert states["web_search"]["rankable"] is False
    assert states["net_ping"]["status"] == "unknown"
    assert states["net_ping"]["rankable"] is True
    assert states["email_summarize"]["status"] == "degraded"
    assert states["email_summarize"]["rankable"] is False

    searxng_down = availability.ConnectivitySnapshot(
        internet=True,
        services={"ollama": True, "searxng": False},
        observed_at=11.0,
    )
    assert availability.describe_availability(
        "web_search", searxng_down, inventory=inventory
    )["status"] == "unavailable"
    assert availability.describe_availability(
        "web_browse", searxng_down, inventory=inventory
    )["status"] == "available"

    empty_router = SimpleNamespace(route_tools=_route_empty)
    with (
        patch.dict(sys.modules, {"tool_router": empty_router}),
        patch.object(selection.db, "get_setting", return_value="28"),
        patch.object(
            selection.tool_availability,
            "get_snapshot",
            AsyncMock(return_value=offline),
        ),
        patch.object(
            selection,
            "rank_capabilities",
            return_value=[("web_search", 10.0), ("calculator", 9.0)],
        ),
    ):
        generic = _names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "aide-moi avec cette demande"}], "agent"
        )))
        assert "web_search" not in generic
        assert {"calculator", "tool_search"} <= generic

        explicit = _names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "cherche sur le web les actualites"}], "agent"
        )))
        assert {"web_search", "web_browse", "tool_search"} <= explicit

    with patch.object(
        tools.tool_availability if hasattr(tools, "tool_availability") else availability,
        "get_snapshot",
        AsyncMock(return_value=offline),
    ):
        result = asyncio.run(tools.execute_tool_search({"query": "web_search", "limit": 3}))
    assert result["connectivity"]["internet"] is False
    assert result["candidates"][0]["name"] == "web_search"
    assert result["candidates"][0]["availability"]["status"] == "unavailable"

    with (
        patch.object(
            selection.tool_availability,
            "get_snapshot",
            AsyncMock(return_value=offline),
        ),
        patch.object(
            selection.tool_availability,
            "availability_map",
            side_effect=availability.ToolDependencyInventoryError("manifest absent"),
        ),
        patch.dict(sys.modules, {"tool_router": empty_router}),
        patch.object(selection.db, "get_setting", return_value="28"),
    ):
        fail_open = _names(asyncio.run(selection.filter_relevant_tools(
            [{"role": "user", "content": "calcule 2 plus 2"}], "agent"
        )))
    assert "calculator" in fail_open

    print("Tool Availability OK - 364 outils, degradation et ranking hors ligne.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
