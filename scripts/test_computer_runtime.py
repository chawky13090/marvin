"""Contrats dÃ©terministes du Computer Runtime unifiÃ©."""

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
from tool_domains.pc_control import _select_window_for_focus


async def _run() -> None:
    browser_title = (
        101,
        "Brasserie de l'Archeveche - Aix-en-Provence - Google Chrome",
    )
    assert _select_window_for_focus(
        "Brasserie de l'Archeveche | Aix-en-Provence - Google Chrome",
        [(100, "Marvin - Google Chrome"), browser_title],
    ) == browser_title
    assert _select_window_for_focus(
        "rapport production",
        [(100, "Rapport production - A"), (101, "Rapport production - B")],
    ) is None

    calls: list[tuple[str, dict]] = []
    state = {"saved": False}

    def fake(name):
        async def execute(arguments):
            calls.append((name, dict(arguments)))
            if name == "pc_window_list":
                return {"success": True, "windows": [{"title": "Bloc-notes"}]}
            if name == "pc_gui_read":
                label = "EnregistrÃ©" if state["saved"] else "Enregistrer"
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
        {"action": "observe", "window": "Bloc-notes", "visual": False}
    )
    assert observed["success"] is True
    assert observed["engine"] == "windows_hybrid"
    element_ref = observed["result"]["ui"]["elements"][0]["element_ref"]

    clicked = await computer_runtime.execute(
        {
            "action": "click",
            "element_ref": element_ref,
            "confirmed": True,
            "expected": "EnregistrÃ©",
            "visual": False,
        }
    )
    assert clicked["success"] is True
    assert clicked["verified"] is True
    assert clicked["needs_repair"] is False
    assert clicked["before"] and clicked["observation"]

    failed_verification = await computer_runtime.execute(
        {"action": "verify", "window": "Bloc-notes", "expected": "Absent", "visual": False}
    )
    assert failed_verification["verified"] is False
    assert failed_verification["needs_repair"] is True

    original_observe = web_browser.computer_observe
    original_navigate = web_browser.computer_navigate
    original_act = web_browser.computer_act
    browser_actions: list[tuple[str, dict]] = []

    async def browser_observe(max_elements=80):
        return {
            "success": True,
            "title": "Documentation",
            "text": "Marvin",
            "width": 1280,
            "height": 900,
            "image": "data:image/png;base64,QUJDRA==",
            "elements": [{"role": "link", "name": "Documentation", "index": 0}],
        }

    async def browser_navigate(url):
        return {
            "success": True,
            "title": "Documentation",
            "url": url,
            "text": "Documentation Marvin",
        }

    async def browser_act(action, **arguments):
        browser_actions.append((action, arguments))
        return await browser_observe()

    web_browser.computer_observe = browser_observe
    web_browser.computer_navigate = browser_navigate
    web_browser.computer_act = browser_act
    try:
        browser_state = await computer_runtime.execute(
            {"action": "observe", "surface": "browser"}
        )
        browser_frame = browser_state["result"]["frame_id"]
        browser_ref = browser_state["result"]["elements"][0]["element_ref"]
        assert browser_frame.startswith("fr_")
        browser_click = await computer_runtime.execute(
            {
                "action": "click",
                "surface": "browser",
                "frame_id": browser_frame,
                "x": 10,
                "y": 20,
                "visual": True,
            }
        )
        assert browser_click["success"] is True
        assert browser_actions[-1][1]["x"] == 10
        assert browser_actions[-1][1]["y"] == 20
        semantic_click = await computer_runtime.execute(
            {"action": "click", "element_ref": browser_ref}
        )
        assert semantic_click["success"] is True
        assert browser_actions[-1][1]["control_type"] == "link"

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
        web_browser.computer_act = original_act

    assert "computer_control" in tools.TOOLS_REGISTRY
    assert any(
        item["function"]["name"] == "computer_control" for item in tools.TOOLS_SPEC
    )
    assert CONDITIONAL_TOOL_SAFE_ACTIONS["computer_control"] == frozenset(
        {"observe", "verify", "screenshot", "list_windows", "wait"}
    )
    missing_commitment = await computer_runtime.execute(
        {"action": "commit", "surface": "browser", "name": "Réserver"}
    )
    assert missing_commitment["needs_repair"] is True
    assert "commitment_summary" in missing_commitment["error"]
    assert any(name == "pc_gui_click" for name, _ in calls)


if __name__ == "__main__":
    asyncio.run(_run())
    print("Computer Runtime OK - observe, act, verify, repair et moteurs bornÃ©s.")
