"""Contrats déterministes du Computer Runtime unifié."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import computer_runtime
import tools
import web_browser
from config import CONDITIONAL_TOOL_SAFE_ACTIONS


async def _run() -> None:
    calls: list[tuple[str, dict]] = []
    state = {"saved": False}

    def fake(name):
        async def execute(arguments):
            calls.append((name, dict(arguments)))
            if name == "pc_window_list":
                return {"success": True, "windows": [{"title": "Bloc-notes"}]}
            if name == "pc_gui_read":
                label = "Enregistré" if state["saved"] else "Enregistrer"
                return {
                    "success": True,
                    "window_title": "Bloc-notes",
                    "elements": [{"control_type": "Button", "name": label}],
                }
            if name == "pc_gui_click":
                state["saved"] = True
                return {"success": True}
            if name == "web_browser_open":
                return {
                    "success": True,
                    "title": "Documentation",
                    "url": arguments["url"],
                    "text": "Documentation Marvin",
                }
            return {"success": True}

        return execute

    computer_runtime.configure(
        {
            name: fake(name)
            for name in (
                "pc_app_launch",
                "pc_window_list",
                "pc_window_focus",
                "pc_gui_read",
                "pc_gui_click",
                "pc_gui_type",
                "pc_screenshot",
                "web_browser_open",
            )
        }
    )

    observed = await computer_runtime.execute(
        {"action": "observe", "window": "Bloc-notes"}
    )
    assert observed["success"] is True
    assert observed["engine"] == "windows_uia"

    clicked = await computer_runtime.execute(
        {
            "action": "click",
            "window": "Bloc-notes",
            "control_type": "Button",
            "name": "Enregistrer",
            "confirmed": True,
            "expected": "Enregistré",
        }
    )
    assert clicked["success"] is True
    assert clicked["verified"] is True
    assert clicked["needs_repair"] is False
    assert clicked["before"] and clicked["observation"]

    failed_verification = await computer_runtime.execute(
        {"action": "verify", "window": "Bloc-notes", "expected": "Absent"}
    )
    assert failed_verification["verified"] is False
    assert failed_verification["needs_repair"] is True

    original_observe = web_browser.computer_observe
    original_navigate = web_browser.computer_navigate

    async def browser_observe(max_elements=80):
        return {"success": True, "title": "Documentation", "text": "Marvin"}

    async def browser_navigate(url):
        return {
            "success": True,
            "title": "Documentation",
            "url": url,
            "text": "Documentation Marvin",
        }

    web_browser.computer_observe = browser_observe
    web_browser.computer_navigate = browser_navigate
    try:
        navigated = await computer_runtime.execute(
            {
                "action": "navigate",
                "surface": "browser",
                "target": "https://example.com",
                "expected": "Marvin",
                "confirmed": True,
            }
        )
        assert navigated["success"] is True
        assert navigated["engine"] == "playwright"
        assert navigated["verified"] is True
    finally:
        web_browser.computer_observe = original_observe
        web_browser.computer_navigate = original_navigate

    assert "computer_control" in tools.TOOLS_REGISTRY
    assert any(
        item["function"]["name"] == "computer_control" for item in tools.TOOLS_SPEC
    )
    assert CONDITIONAL_TOOL_SAFE_ACTIONS["computer_control"] == frozenset(
        {"observe", "verify", "screenshot", "list_windows"}
    )
    assert any(name == "pc_gui_click" for name, _ in calls)


if __name__ == "__main__":
    asyncio.run(_run())
    print("Computer Runtime OK - observe, act, verify, repair et moteurs bornés.")
