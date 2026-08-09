"""Régressions déterministes du domaine de contrôle PC."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
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


class _VerifiedProcess:
    def __init__(self, pid: int, *, timeout: bool = False):
        self.pid = pid
        self.timeout = timeout
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float):
        assert timeout == 5
        if self.timeout:
            raise pc_control.psutil.TimeoutExpired(timeout, self.pid)
        return 0


async def _run() -> None:
    previous_program_files = os.environ.get("ProgramFiles")
    with tempfile.TemporaryDirectory() as temp_root:
        app_dir = Path(temp_root) / "MarvinResolverFixture"
        app_dir.mkdir()
        (app_dir / "Resolver64.exe").touch()
        (app_dir / "unins000.exe").touch()
        os.environ["ProgramFiles"] = temp_root
        try:
            kind, target = pc_control._find_app_target("MarvinResolverFixture")
        finally:
            if previous_program_files is None:
                os.environ.pop("ProgramFiles", None)
            else:
                os.environ["ProgramFiles"] = previous_program_files
        assert kind == "exe"
        assert target and target.endswith("Resolver64.exe")

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
    original_process = pc_control.psutil.Process
    verified_process = _VerifiedProcess(123)
    try:
        pc_control.psutil.Process = lambda _pid: verified_process
        verified = await pc_control.execute_pc_process_kill(
            {"pid": 123, "confirmed": True}
        )
        assert verified["success"] is True
        assert verified["verification"] == {"pid": 123, "state": "absent"}
        assert verified_process.terminated is True

        timeout_process = _VerifiedProcess(124, timeout=True)
        pc_control.psutil.Process = lambda _pid: timeout_process
        not_verified = await pc_control.execute_pc_process_kill(
            {"pid": 124, "confirmed": True}
        )
        assert "Résultat non validé" in not_verified["error"]
        assert not_verified["verification"]["state"] == "still_running"
    finally:
        pc_control.psutil.Process = original_process
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
