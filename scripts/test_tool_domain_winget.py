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


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine Winget OK")
