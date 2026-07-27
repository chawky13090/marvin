"""Régressions déterministes du nettoyage Catharsis."""

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
from tool_domains import catharsis


async def _run() -> None:
    calls: list[dict] = []

    async def fake_powershell(args: dict) -> dict:
        calls.append(args)
        if "ConvertTo-Json" in args["script"]:
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "temp_user": 1048576,
                        "recycle_bin": -10,
                        "injected_category": 999999,
                        "chrome_cache": "invalide",
                    }
                ),
            }
        return {"returncode": 0, "stdout": "OK", "stderr": ""}

    catharsis.configure(run_powershell=fake_powershell)

    scanned = await catharsis.execute_catharsis_scan({})
    assert scanned["success"] is True
    assert scanned["total_mb"] == 1.0
    assert {item["id"] for item in scanned["categories"]} == {
        "temp_user",
        "recycle_bin",
        "chrome_cache",
    }

    calls.clear()
    assert "liste attendue" in (
        await catharsis.execute_catharsis_clean({"categories": "temp_user"})
    )["error"]
    assert calls == []
    assert "categories" in (
        await catharsis.execute_catharsis_clean(
            {"categories": ["C:\\Users\\*; Remove-Item C:\\*"], "confirmed": True}
        )
    )["error"]
    assert calls == []

    confirmation = await catharsis.execute_catharsis_clean(
        {"categories": ["temp_user", "temp_user", "recycle_bin"]}
    )
    assert confirmation["requiresConfirmation"] is True
    assert "2 catégorie" in confirmation["message"]
    cleaned = await catharsis.execute_catharsis_clean(
        {
            "categories": ["temp_user", "temp_user", "recycle_bin"],
            "confirmed": True,
        }
    )
    assert cleaned["success"] is True
    assert cleaned["cleaned"] == ["temp_user", "recycle_bin"]

    for name in ("catharsis_scan", "catharsis_clean"):
        implementation = getattr(catharsis, f"execute_{name}")
        assert getattr(tools, f"execute_{name}") is implementation
        assert tools.TOOLS_REGISTRY[name] is implementation


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine Catharsis OK")
