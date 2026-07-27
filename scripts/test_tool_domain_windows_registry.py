"""Régressions déterministes du registre Windows et des points de restauration."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import windows_registry


async def _run() -> None:
    calls: list[dict] = []
    original_backup = windows_registry._reg_backup

    async def fake_powershell(args: dict) -> dict:
        calls.append(args)
        return {"returncode": 0, "stdout": "OK", "stderr": ""}

    async def fake_backup(_path: str) -> str:
        return "C:\\backup.reg"

    windows_registry.configure(run_powershell=fake_powershell)
    windows_registry._reg_backup = fake_backup
    try:
        assert "path" in (
            await windows_registry.execute_registry_get(
                {"path": "HKLM:\\SOFTWARE\\Test'; Remove-Item C:\\*"}
            )
        )["error"]
        assert calls == []
        assert "name" in (
            await windows_registry.execute_registry_get(
                {"path": "HKLM:\\SOFTWARE\\Test", "name": "A'; Write-Host bad"}
            )
        )["error"]
        assert "Type de registre" in (
            await windows_registry.execute_registry_set(
                {
                    "path": "HKCU:\\Software\\Test",
                    "name": "Value",
                    "value": 1,
                    "type": "Script",
                }
            )
        )["error"]
        assert "Valeur invalide" in (
            await windows_registry.execute_registry_set(
                {
                    "path": "HKCU:\\Software\\Test",
                    "name": "Value",
                    "value": -1,
                    "type": "DWord",
                }
            )
        )["error"]

        changed = await windows_registry.execute_registry_set(
            {
                "path": "HKCU:\\Software\\Test",
                "name": "Greeting",
                "value": "O'Brien; valeur",
                "type": "String",
                "confirmed": True,
            }
        )
        assert changed["success"] is True
        assert "'O''Brien; valeur'" in calls[-1]["script"]

        restored = await windows_registry.execute_system_restore_point(
            {"description": "Avant; test d'O'Brien", "confirmed": True}
        )
        assert restored["success"] is True
        assert "'Avant; test d''O''Brien'" in calls[-1]["script"]

        for name in (
            "registry_get",
            "registry_backup",
            "registry_set",
            "system_restore_point",
        ):
            implementation = getattr(windows_registry, f"execute_{name}")
            assert getattr(tools, f"execute_{name}") is implementation
            assert tools.TOOLS_REGISTRY[name] is implementation
        assert tools._reg_backup is windows_registry._reg_backup or (
            tools._reg_backup is original_backup
        )
    finally:
        windows_registry._reg_backup = original_backup


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine registre Windows OK")
