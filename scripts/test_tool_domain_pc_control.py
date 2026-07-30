"""Régressions déterministes du domaine de contrôle PC."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import pc_control


class _FakeElementInfo:
    control_type = "Document"
    automation_id = ""

    class element:
        CurrentIsPassword = False


class _FakeDocument:
    element_info = _FakeElementInfo()

    @staticmethod
    def window_text() -> str:
        return ""

    @staticmethod
    def is_enabled() -> bool:
        return True

    @staticmethod
    def is_visible() -> bool:
        return True


class _FakeWindow:
    @staticmethod
    def descendants():
        return [_FakeDocument()]


class _ResolveElementInfo:
    control_type = "Button"
    automation_id = "submit-booking"


class _ResolveControl:
    element_info = _ResolveElementInfo()


class _ResolveWindow:
    calls: list[dict] = []

    @classmethod
    def descendants(cls, **kwargs):
        cls.calls.append(kwargs)
        return [_ResolveControl()]


async def _run() -> None:
    browse = await pc_control.execute_pc_browse({})
    assert browse["success"] is True
    assert isinstance(browse["roots"], list)
    assert "command" in (await pc_control.execute_pc_run_command({}))["error"]
    assert "timeout" in (
        await pc_control.execute_pc_run_command(
            {"command": "echo test", "timeout": "long", "confirmed": True}
        )
    )["error"]
    assert "script" in (await pc_control.execute_pc_run_powershell({}))["error"]
    assert "timeout" in (
        await pc_control.execute_pc_run_powershell(
            {"script": "Get-Date", "timeout": "long", "confirmed": True}
        )
    )["error"]
    assert "PID ou nom" in (await pc_control.execute_pc_process_kill({}))["error"]
    assert "PID invalide" in (
        await pc_control.execute_pc_process_kill(
            {"pid": "abc", "confirmed": True}
        )
    )["error"]
    confirmation = await pc_control.execute_pc_process_kill({"pid": 123})
    assert confirmation["requiresConfirmation"] is True
    assert "max_elements" in (
        await pc_control.execute_pc_gui_read({"max_elements": "beaucoup"})
    )["error"]
    assert "match_index" in (
        await pc_control.execute_pc_gui_click(
            {"control_type": "Button", "match_index": "premier"}
        )
    )["error"]
    assert "Document" in pc_control._GUI_INTERACTIVE_TYPES
    original_get_window = pc_control._gui_get_window_sync
    try:
        pc_control._gui_get_window_sync = lambda _search: (_FakeWindow(), "Fenêtre test")
        ui_tree = pc_control._gui_read_sync("test", 10)
    finally:
        pc_control._gui_get_window_sync = original_get_window
    assert ui_tree["count"] == 1
    assert ui_tree["elements"][0]["control_type"] == "Document"
    assert ui_tree["elements"][0]["match_index"] == 0

    try:
        pc_control._gui_get_window_sync = (
            lambda _search: (_ResolveWindow(), "Fenêtre test")
        )
        _, _, resolved = pc_control._gui_resolve_sync(
            "test", "Button", "", "submit-booking", 0
        )
    finally:
        pc_control._gui_get_window_sync = original_get_window
    assert resolved.element_info.automation_id == "submit-booking"
    assert _ResolveWindow.calls[-1] == {"control_type": "Button"}

    public_names = [
        name.removeprefix("execute_")
        for name in dir(pc_control)
        if name.startswith("execute_pc_")
    ]
    assert len(public_names) == 21
    for public_name in public_names:
        implementation = getattr(pc_control, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation
    assert tools.execute_win_network_config is not None


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine contrôle PC OK")
