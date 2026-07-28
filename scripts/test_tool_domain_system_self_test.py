"""Régressions de l'auto-diagnostic borné, déterministe et sans effet de bord."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import system_self_test


async def main() -> None:
    calls: list[str] = []

    async def succeeds(_args: dict[str, Any]) -> dict[str, Any]:
        calls.append("ok")
        return {"success": True}

    async def returns_error(_args: dict[str, Any]) -> dict[str, Any]:
        calls.append("error")
        return {"error": "indisponible"}

    async def crashes(_args: dict[str, Any]) -> dict[str, Any]:
        calls.append("crash")
        raise RuntimeError("panne injectée")

    async def web(_args: dict[str, Any]) -> dict[str, Any]:
        calls.append("web")
        return {"success": True}

    probes = (
        system_self_test.Probe("local", "ok", {}),
        system_self_test.Probe("local", "error", {}),
        system_self_test.Probe("local", "crash", {}),
        system_self_test.Probe("local", "missing", {}),
        system_self_test.Probe("web", "web", {}, requires_web=True),
    )
    registry = {
        "ok": succeeds,
        "error": returns_error,
        "crash": crashes,
        "web": web,
    }
    system_self_test.configure(
        registry_provider=lambda: registry,
        probes=probes,
    )

    local = await system_self_test.run({})
    assert local["success"] is True
    assert local["tested"] == 4
    assert local["ok"] == 1
    assert local["failed"] == 3
    assert [item["tool"] for item in local["results"]] == [
        "ok",
        "error",
        "crash",
        "missing",
    ]
    assert [item["status"] for item in local["results"]] == [
        "ok",
        "erreur",
        "crash",
        "absent",
    ]
    assert "web" not in calls
    assert local["policy"]["read_only_catalog"] is True
    assert local["policy"]["max_concurrency"] == 4

    with_web = await system_self_test.run({"include_web": True, "category": "web"})
    assert with_web["tested"] == 1
    assert with_web["ok"] == 1
    assert calls[-1] == "web"

    assert "booléen" in (
        await system_self_test.run({"include_web": "oui"})
    )["error"]
    unknown = await system_self_test.run({"category": "inconnue"})
    assert "error" in unknown
    assert "local" in unknown["available_categories"]

    original_timeout = system_self_test._PER_TOOL_TIMEOUT_SECONDS
    try:
        async def too_slow(_args: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(0.05)
            return {"success": True}

        system_self_test._PER_TOOL_TIMEOUT_SECONDS = 0.01
        system_self_test.configure(
            registry_provider=lambda: {"slow": too_slow},
            probes=(system_self_test.Probe("local", "slow", {}),),
        )
        timed_out = await system_self_test.run({})
        assert timed_out["results"][0]["status"] == "timeout"
    finally:
        system_self_test._PER_TOOL_TIMEOUT_SECONDS = original_timeout

    system_self_test.configure(
        registry_provider=lambda: tools.TOOLS_REGISTRY,
    )
    assert tools.execute_system_self_test is system_self_test.run
    assert tools.TOOLS_REGISTRY["system_self_test"] is system_self_test.run


if __name__ == "__main__":
    asyncio.run(main())
    print("System self-test OK - catalogue sûr, ordre, erreurs, timeout et façade.")
