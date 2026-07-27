"""Régressions déterministes du domaine diagnostic PC."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import pc_diagnostics


async def _run() -> None:
    async def fake_powershell(_args: dict) -> dict:
        return {"returncode": 0, "stdout": "[]"}

    async def fake_search(args: dict) -> dict:
        return {
            "success": True,
            "results": [{"title": "Pilote officiel", "url": "https://example.test"}],
            "query": args["query"],
        }

    pc_diagnostics.configure(
        run_powershell=fake_powershell, web_search=fake_search
    )

    assert "days" in (
        await pc_diagnostics.execute_pc_health_trend({"days": "long"})
    )["error"]
    assert "invalides" in (
        await pc_diagnostics.execute_pc_event_log_errors({"days": "long"})
    )["error"]
    assert "invalides" in (
        await pc_diagnostics.execute_pc_tool_reliability({"min_calls": "plusieurs"})
    )["error"]
    assert "component" in (
        await pc_diagnostics.execute_pc_driver_check({"component": None})
    )["error"]
    driver = await pc_diagnostics.execute_pc_driver_check(
        {"component": "GPU Test", "installed_version": 123}
    )
    assert driver["success"] is True
    assert driver["installed_version"] == "123"
    assert "conversation_id" in (
        await pc_diagnostics.execute_pc_conversation_trace({})
    )["error"]

    public_names = [
        name.removeprefix("execute_")
        for name in dir(pc_diagnostics)
        if name.startswith("execute_pc_")
    ]
    assert len(public_names) == 10
    for public_name in public_names:
        implementation = getattr(pc_diagnostics, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine diagnostic PC OK")
