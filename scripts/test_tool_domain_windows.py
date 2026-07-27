"""Régressions déterministes du domaine d'outils Windows."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import windows


async def _run() -> None:
    calls: list[dict] = []

    async def fake_runner(args: dict) -> dict:
        calls.append(args)
        script = args["script"]
        if "Get-Service -Name" in script:
            return {"returncode": 0, "stdout": "Spooler"}
        if "Get-EventLog" in script:
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    [{"EntryType": "Error", "Source": "Test", "EventID": 1}]
                ),
            }
        if "Win32_OperatingSystem" in script:
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "LastBoot": "2026-07-27 10:00:00",
                        "Days": 1,
                        "Hours": 2,
                        "Minutes": 3,
                        "TotalHours": 26.1,
                    }
                ),
            }
        return {"returncode": 0, "stdout": "[]"}

    windows.configure(run_powershell=fake_runner)
    invalid_log = await windows.execute_win_event_log(
        {"log": "System'; Remove-Item C:\\", "max_events": 20}
    )
    assert "Journal invalide" in invalid_log["error"]
    assert not calls
    invalid_count = await windows.execute_win_event_log(
        {"log": "System", "max_events": "beaucoup"}
    )
    assert "max_events" in invalid_count["error"]
    events = await windows.execute_win_event_log(
        {"log": "system", "max_events": 500, "level": "error"}
    )
    assert events["success"] is True and events["count"] == 1
    assert "-Newest 200" in calls[-1]["script"]

    confirmation = await windows.execute_win_service_action(
        {"name": "Spooler", "action": "restart"}
    )
    assert confirmation["requiresConfirmation"] is True
    queried = await windows.execute_win_service_action(
        {"name": "Spooler", "action": "status"}
    )
    assert queried["success"] is True

    windows._win_diag_cache.clear()
    first = await windows.execute_win_uptime({})
    second = await windows.execute_win_uptime({})
    assert first["success"] is True and second["success"] is True
    assert second["human"] == "1j 2h 3min"

    names = [
        name.removeprefix("execute_")
        for name in dir(windows)
        if name.startswith("execute_win_")
    ]
    assert len(names) == 14
    for public_name in names:
        implementation = getattr(windows, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine Windows OK")
