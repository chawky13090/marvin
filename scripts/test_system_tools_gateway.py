"""Contrats HTTP des 25 appels d'outils système via le gateway commun."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import system_tools


async def main_async() -> None:
    calls = []

    async def execute(name, arguments, **options):
        calls.append((name, arguments, options))
        return SimpleNamespace(result={"success": True, "tool": name})

    with patch.object(system_tools.tool_runtime, "execute", side_effect=execute):
        await system_tools.winget_search("git", "winget", 5)
        await system_tools.winget_upgrades()
        await system_tools.winget_installed("python")
        await system_tools.winget_install({"id": "Git.Git"})
        await system_tools.winget_upgrade({})
        await system_tools.winget_uninstall({"id": "Git.Git"})
        await system_tools.pantheon_telemetry_status()
        await system_tools.pantheon_telemetry_set({"action": "disable"})
        await system_tools.pantheon_debloat_list()
        await system_tools.pantheon_debloat_remove({"packages": ["example"]})
        await system_tools.pantheon_network_status()
        await system_tools.pantheon_network_apply()
        await system_tools.pantheon_restore_point({"description": "Test"})
        await system_tools.catharsis_scan()
        await system_tools.catharsis_clean({"categories": ["temp_user"]})
        status = await system_tools.codex_status()
        await system_tools.codex_power({"plan": "balanced"})
        await system_tools.codex_dark({"action": "toggle"})
        await system_tools.codex_firewall({"action": "enable"})
        await system_tools.codex_hibernation({"action": "disable"})
        await system_tools.codex_adapter({"action": "disable", "name": "Ethernet"})

    assert len(calls) == 25
    assert set(status) == {"power", "dark", "firewall", "hibernation", "adapters"}
    assert all(call[2]["source"] == "system_ui" for call in calls)
    mutations = [call for call in calls if call[2]["confirmed_by_ui"]]
    assert len(mutations) == 13
    assert all("confirmed" not in call[1] for call in mutations)
    safe_actions = {
        ("tweak_telemetry", "status"),
        ("tweak_network_harden", "status"),
        ("os_power_plan", "get"),
        ("os_dark_mode", "get"),
        ("os_firewall", "status"),
        ("os_hibernation", "status"),
        ("os_network_adapters", "list"),
    }
    observed_safe = {
        (name, arguments.get("action"))
        for name, arguments, options in calls
        if not options["confirmed_by_ui"] and arguments.get("action")
    }
    assert observed_safe == safe_actions


def main() -> int:
    asyncio.run(main_async())
    print("System Tools Gateway OK - 25 appels, 13 mutations et 7 lectures mixtes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
