"""Régressions déterministes du domaine Winget."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import winget


async def _run() -> None:
    original_run = winget._winget_run
    original_installed_exact = winget._installed_exact
    original_wait_for_inventory_state = winget._wait_for_inventory_state
    calls: list[list[str]] = []
    try:
        def fake_run(args: list[str], timeout: int = 90) -> dict:
            calls.append(args)
            return {
                "ok": True,
                "code": 0,
                "stdout": (
                    "Name                 Id                 Version Source\n"
                    "------------------------------------------------------\n"
                    "Git                  Git.Git            2.50.0  winget\n"
                ),
                "stderr": "",
            }

        winget._winget_run = fake_run

        assert "limit" in (
            await winget.execute_winget_search({"query": "git", "limit": 0})
        )["error"]
        assert "Source Winget invalide" in (
            await winget.execute_winget_search(
                {"query": "git", "source": "--accept-package-agreements"}
            )
        )["error"]
        searched = await winget.execute_winget_search(
            {"query": "git", "limit": 10, "source": "winget"}
        )
        assert searched["success"] is True
        assert calls[-1][-2:] == ["--source", "winget"]

        assert "Identifiant Winget invalide" in (
            await winget.execute_winget_install({"id": "--silent"})
        )["error"]
        confirmation = await winget.execute_winget_install({"id": "Git.Git"})
        assert confirmation["requiresConfirmation"] is True
        install_states = iter((
            None,
            {"name": "Git", "id": "Git.Git", "version": "2.50.0"},
        ))
        async def installed(package_id: str):
            state = next(install_states)
            if state:
                state["id"] = package_id
            return state
        winget._installed_exact = installed
        installed_result = await winget.execute_winget_install(
            {"id": "Git.Git", "confirmed": True}
        )
        assert installed_result["success"] is True
        assert installed_result["verification"]["observed"] == "installed"
        assert calls[-1][0] == "install"

        async def already_installed(package_id: str):
            return {"name": "Git", "id": package_id, "version": "2.50.0"}
        winget._installed_exact = already_installed
        calls_before = len(calls)
        unchanged = await winget.execute_winget_install(
            {"id": "Git.Git", "confirmed": True}
        )
        assert unchanged["success"] is True and unchanged["changed"] is False
        assert len(calls) == calls_before

        states = iter(({"name": "Git", "id": "Git.Git"}, None))
        async def uninstall_state(_package_id: str):
            return next(states)
        winget._installed_exact = uninstall_state
        removed = await winget.execute_winget_uninstall(
            {"id": "Git.Git", "confirmed": True}
        )
        assert removed["success"] is True and removed["changed"] is True
        assert removed["verification"]["observed"] == "absent"
        assert calls[-1][:4] == ["uninstall", "--id", "Git.Git", "-e"]

        async def still_present(_package_id: str):
            return {"name": "Opera", "id": "Opera.Opera", "version": "1"}

        async def pending_inventory(_package_id: str, **_kwargs):
            return await still_present(_package_id), False, 11

        winget._installed_exact = still_present
        winget._wait_for_inventory_state = pending_inventory
        pending = await winget.execute_winget_uninstall(
            {"id": "Opera.Opera", "confirmed": True}
        )
        assert pending["success"] is False
        assert pending["action_outcome_unknown"] is True
        assert pending["interaction_may_be_required"] is True
        assert pending["retry_allowed"] is False
        assert pending["verification"]["observed"] == "still_installed_after_bounded_wait"
        assert pending["verification"]["attempts"] == 11
        assert "ne relancez pas automatiquement" in pending["message"]

        def failed_run(args: list[str], timeout: int = 90) -> dict:
            calls.append(args)
            return {"ok": False, "code": 1603, "stdout": "", "stderr": "failure"}

        winget._winget_run = failed_run
        failed = await winget.execute_winget_uninstall(
            {"id": "Opera.Opera", "confirmed": True}
        )
        assert failed["success"] is False
        assert failed["action_outcome_unknown"] is False
        assert failed["retry_allowed"] is True
        assert "Identifiant Winget invalide" in (
            await winget.execute_winget_upgrade({"id": "--all"})
        )["error"]
        assert "Identifiant Winget invalide" in (
            await winget.execute_winget_uninstall({"id": "--all"})
        )["error"]

        public_names = [
            name.removeprefix("execute_")
            for name in dir(winget)
            if name.startswith("execute_winget_")
        ]
        assert len(public_names) == 6
        for public_name in public_names:
            implementation = getattr(winget, f"execute_{public_name}")
            assert getattr(tools, f"execute_{public_name}") is implementation
            assert tools.TOOLS_REGISTRY[public_name] is implementation
    finally:
        winget._winget_run = original_run
        winget._installed_exact = original_installed_exact
        winget._wait_for_inventory_state = original_wait_for_inventory_state


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine Winget OK")
