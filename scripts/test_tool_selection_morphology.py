"""Validate the preregistered bounded morphology without executing tools."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_tool_selection as selection
import capability_discovery


POLICY = ROOT / "benchmarks/tool-selection/v1.4/morphology-preregistration.json"


def _normalized(value: str) -> str:
    return selection._strip_accents(value.lower())


async def _selected_names(prompt: str) -> set[str]:
    original_route = None
    import tool_router

    original_route = tool_router.route_tools

    async def no_semantic_route(_query: str) -> dict:
        return {"semantic": set(), "learned": set(), "semantic_scores": {}}

    tool_router.route_tools = no_semantic_route
    original_setting = selection.db.get_setting
    selection.db.get_setting = lambda key: "18" if key == "max_tools" else original_setting(key)
    try:
        selected = await selection.filter_relevant_tools(
            [{"role": "user", "content": prompt}],
            "agent",
        )
    finally:
        tool_router.route_tools = original_route
        selection.db.get_setting = original_setting
    return {
        str(specification.get("function", {}).get("name") or "")
        for specification in selected
    }


def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["status"] == "frozen_before_product_change"
    canaries = policy["development_canaries"]

    for text in canaries["must_match_install_prefix"]:
        assert selection._keyword_present("install*", _normalized(text)), text
    for text in canaries["must_not_match_install_prefix"]:
        assert not selection._keyword_present("install*", _normalized(text)), text
    for text in canaries["ordinary_keyword_must_not_become_fuzzy"]:
        assert not selection._keyword_present("supprimer", _normalized(text)), text
        assert not selection._keyword_present("rechercher", _normalized(text)), text

    assert selection._keyword_present("ip", "multiplie") is False
    assert selection._prefix_keyword_present("short", "shorter") is False

    install_names = asyncio.run(_selected_names("Instaler le logiciel VLC avec Winget"))
    assert {"winget_search", "winget_install"} <= install_names

    launch_names = asyncio.run(_selected_names("Démarre l'application Bloc-notes"))
    assert "windows_task" in launch_names

    update_names = asyncio.run(_selected_names("Liste les mises à jour disponibles"))
    assert "winget_list_upgrades" in update_names

    registry_names = {
        str(specification.get("function", {}).get("name") or "")
        for specification in selection.TOOLS_SPEC
    }
    assert len(selection.TOOLS_SPEC) == 364
    assert all(name in registry_names for name in install_names | launch_names | update_names)

    for name in (
        "pc_app_launch",
        "pc_installed_software",
        "winget_list_upgrades",
        "winget_upgrade",
    ):
        profile = capability_discovery.profile_for(name)
        assert profile.title != name.replace("_", " ").capitalize()
        assert profile.use_when

    print(
        "Tool Selection Morphology OK - positives="
        f"{len(canaries['must_match_install_prefix'])} negatives="
        f"{len(canaries['must_not_match_install_prefix'])} registry=364 budget=18"
    )


if __name__ == "__main__":
    main()
