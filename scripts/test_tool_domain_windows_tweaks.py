"""Régressions déterministes des tweaks Windows."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import windows_tweaks


async def _run() -> None:
    calls: list[dict] = []

    async def fake_powershell(args: dict) -> dict:
        calls.append(args)
        if "Get-AppxPackage | Select-Object" in args["script"]:
            return {
                "returncode": 0,
                "stdout": "Microsoft.BingNews\nMicrosoft.WindowsMaps\n",
                "stderr": "",
            }
        return {"returncode": 0, "stdout": "OK", "stderr": ""}

    async def fake_registry(_args: dict) -> dict:
        return {"success": True, "value": "0"}

    async def fake_backup(_path: str) -> str:
        return "C:\\backup.reg"

    windows_tweaks.configure(
        run_powershell=fake_powershell,
        registry_get=fake_registry,
        reg_backup=fake_backup,
    )

    listed = await windows_tweaks.execute_tweak_debloat_list({})
    assert listed["removable"] == ["Microsoft.BingNews", "Microsoft.WindowsMaps"]

    calls.clear()
    invalid = await windows_tweaks.execute_tweak_debloat_remove(
        {"packages": ["Bad'; Remove-Item C:\\*"], "confirmed": True}
    )
    assert "catalogue" in invalid["error"]
    assert calls == []
    assert "liste attendue" in (
        await windows_tweaks.execute_tweak_debloat_remove(
            {"packages": "Microsoft.BingNews"}
        )
    )["error"]

    confirmation = await windows_tweaks.execute_tweak_debloat_remove(
        {"packages": ["Microsoft.BingNews"]}
    )
    assert confirmation["requiresConfirmation"] is True
    removed = await windows_tweaks.execute_tweak_debloat_remove(
        {
            "packages": ["Microsoft.BingNews", "Microsoft.BingNews"],
            "confirmed": True,
        }
    )
    assert removed["success"] is True
    assert removed["removed"] == ["Microsoft.BingNews"]

    telemetry = await windows_tweaks.execute_tweak_telemetry({"action": "disable"})
    assert telemetry["requiresConfirmation"] is True
    assert "action attendue" in (
        await windows_tweaks.execute_tweak_telemetry({"action": "erase"})
    )["error"]

    public_names = [
        name.removeprefix("execute_")
        for name in dir(windows_tweaks)
        if name.startswith("execute_tweak_")
    ]
    assert len(public_names) == 4
    for public_name in public_names:
        implementation = getattr(windows_tweaks, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine tweaks Windows OK")
