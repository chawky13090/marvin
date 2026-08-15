"""Exercise the v1.5 software boundary after hostile K/L/S candidate union."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_tool_selection as selection
import tool_router


POLICY = ROOT / "benchmarks/tool-selection/v1.5/software-intent-boundary-preregistration.json"
ALL_SOFTWARE = set(selection._SOFTWARE_ACTION_TOOLS)


async def _selected(prompt: str) -> set[str]:
    original_route = tool_router.route_tools
    original_setting = selection.db.get_setting
    original_snapshot = selection.tool_availability.get_snapshot
    original_availability_map = selection.tool_availability.availability_map

    async def hostile_semantic(_query: str) -> dict:
        return {
            "semantic": set(ALL_SOFTWARE),
            "learned": set(),
            "semantic_scores": {name: 1.0 for name in ALL_SOFTWARE},
        }

    tool_router.route_tools = hostile_semantic
    selection.db.get_setting = lambda key: "18" if key == "max_tools" else original_setting(key)
    async def all_available_snapshot() -> dict:
        return {}

    selection.tool_availability.get_snapshot = all_available_snapshot
    selection.tool_availability.availability_map = lambda names, _snapshot: {
        name: {"rankable": True} for name in names
    }
    try:
        specifications = await selection.filter_relevant_tools(
            [{"role": "user", "content": prompt}], "agent"
        )
    finally:
        tool_router.route_tools = original_route
        selection.db.get_setting = original_setting
        selection.tool_availability.get_snapshot = original_snapshot
        selection.tool_availability.availability_map = original_availability_map
    return {
        str(item.get("function", {}).get("name") or "")
        for item in specifications
    }


def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    contracts = policy["contracts"]
    mutations = {"winget_install", "winget_upgrade", "winget_uninstall"}

    for expected_intent, prompts in policy["development_canaries"].items():
        for prompt in prompts:
            normalized = selection._strip_accents(prompt.lower())
            actual_intent = selection._software_intent_boundary(normalized)
            assert actual_intent == expected_intent, (prompt, actual_intent, expected_intent)
            names = asyncio.run(_selected(prompt))
            allowed = set(contracts[expected_intent].get("terminal", [])) | set(
                contracts[expected_intent].get("permitted_read_only", [])
            )
            assert names & ALL_SOFTWARE == allowed, (prompt, names & ALL_SOFTWARE, allowed)

    assert selection._software_intent_boundary("installe les dependances python avec pip") is None
    assert selection._software_intent_boundary("mets a jour le document word") is None
    assert not (asyncio.run(_selected("liste les logiciels installes")) & mutations)
    assert not (asyncio.run(_selected("aide-moi avec Winget")) & mutations)
    assert "winget_uninstall" not in asyncio.run(_selected("installe VLC"))
    assert "winget_install" not in asyncio.run(_selected("desinstalle VLC"))
    assert "winget_uninstall" not in asyncio.run(_selected("mets VLC a jour"))
    owner_typo_names = asyncio.run(_selected("mais a jour WinDirStat"))
    assert selection._software_intent_boundary("mais a jour windirstat") == "software.upgrade"
    assert owner_typo_names & ALL_SOFTWARE == {"winget_upgrade"}
    assert len(selection.TOOLS_SPEC) == 364
    print("Tool Selection v1.5 Software Boundary OK - intents=8 hostile_union=closed registry=364")


if __name__ == "__main__":
    main()
