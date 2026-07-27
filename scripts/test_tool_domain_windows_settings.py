"""Régressions déterministes des paramètres Windows."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import windows_settings


async def _run() -> None:
    calls: list[dict] = []

    async def fake_powershell(args: dict) -> dict:
        calls.append(args)
        if "ConvertTo-Json" in args["script"]:
            return {"returncode": 0, "stdout": "[]", "stderr": ""}
        return {"returncode": 0, "stdout": "OK", "stderr": ""}

    async def fake_registry(_args: dict) -> dict:
        return {"success": True, "value": "0"}

    windows_settings.configure(
        run_powershell=fake_powershell,
        registry_get=fake_registry,
    )

    dark = await windows_settings.execute_os_dark_mode({"action": "get"})
    assert dark == {"success": True, "mode": "sombre"}
    assert "plan attendu" in (
        await windows_settings.execute_os_power_plan(
            {"action": "set", "plan": "turbo"}
        )
    )["error"]
    firewall = await windows_settings.execute_os_firewall({"action": "off"})
    assert firewall["requiresConfirmation"] is True

    calls.clear()
    invalid = await windows_settings.execute_os_network_adapters(
        {"action": "disable", "name": "Ethernet'; Remove-Item C:\\*"}
    )
    assert "name" in invalid["error"]
    assert calls == []

    confirmation = await windows_settings.execute_os_network_adapters(
        {"action": "disable", "name": "vEthernet (Default Switch)"}
    )
    assert confirmation["requiresConfirmation"] is True
    applied = await windows_settings.execute_os_network_adapters(
        {
            "action": "disable",
            "name": "vEthernet (Default Switch)",
            "confirmed": True,
        }
    )
    assert applied["success"] is True
    assert "vEthernet (Default Switch)" in calls[-1]["script"]

    public_names = [
        name.removeprefix("execute_")
        for name in dir(windows_settings)
        if name.startswith("execute_os_")
    ]
    assert len(public_names) == 5
    for public_name in public_names:
        implementation = getattr(windows_settings, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine paramètres Windows OK")
