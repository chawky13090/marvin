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


async def _run() -> None:
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
