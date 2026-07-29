"""Adaptateurs HTTP des outils Windows exposés dans les pages système."""

from fastapi import APIRouter, Body

import tool_runtime


router = APIRouter(tags=["system-tools"])


async def _system_tool(name: str, arguments: dict, *, mutation: bool = False):
    return (
        await tool_runtime.execute(
            name,
            arguments,
            source="system_ui",
            confirmed_by_ui=mutation,
        )
    ).result


@router.get("/api/winget/search")
async def winget_search(q: str, source: str | None = None, limit: int = 20):
    args = {"query": q, "limit": limit}
    if source:
        args["source"] = source
    return await _system_tool("winget_search", args)


@router.get("/api/winget/upgrades")
async def winget_upgrades():
    return await _system_tool("winget_list_upgrades", {})


@router.get("/api/winget/installed")
async def winget_installed(q: str | None = None):
    return await _system_tool("winget_list_installed", {"query": q} if q else {})


@router.post("/api/winget/install")
async def winget_install(body: dict = Body(...)):
    return await _system_tool("winget_install", body or {}, mutation=True)


@router.post("/api/winget/upgrade")
async def winget_upgrade(body: dict = Body(default={})):
    return await _system_tool("winget_upgrade", body or {}, mutation=True)


@router.post("/api/winget/uninstall")
async def winget_uninstall(body: dict = Body(...)):
    return await _system_tool("winget_uninstall", body or {}, mutation=True)


@router.get("/api/pantheon/telemetry")
async def pantheon_telemetry_status():
    return await _system_tool("tweak_telemetry", {"action": "status"})


@router.post("/api/pantheon/telemetry")
async def pantheon_telemetry_set(body: dict = Body(...)):
    action = (body or {}).get("action", "disable")
    return await _system_tool(
        "tweak_telemetry", {"action": action}, mutation=True
    )


@router.get("/api/pantheon/debloat")
async def pantheon_debloat_list():
    return await _system_tool("tweak_debloat_list", {})


@router.post("/api/pantheon/debloat/remove")
async def pantheon_debloat_remove(body: dict = Body(...)):
    packages = (body or {}).get("packages") or []
    return await _system_tool(
        "tweak_debloat_remove", {"packages": packages}, mutation=True
    )


@router.get("/api/pantheon/network")
async def pantheon_network_status():
    return await _system_tool("tweak_network_harden", {"action": "status"})


@router.post("/api/pantheon/network/apply")
async def pantheon_network_apply():
    return await _system_tool(
        "tweak_network_harden", {"action": "apply"}, mutation=True
    )


@router.post("/api/pantheon/restore-point")
async def pantheon_restore_point(body: dict = Body(default={})):
    description = (body or {}).get("description", "Marvin — avant optimisation")
    return await _system_tool(
        "system_restore_point", {"description": description}, mutation=True
    )


@router.get("/api/catharsis/scan")
async def catharsis_scan():
    return await _system_tool("catharsis_scan", {})


@router.post("/api/catharsis/clean")
async def catharsis_clean(body: dict = Body(...)):
    categories = (body or {}).get("categories") or []
    return await _system_tool(
        "catharsis_clean", {"categories": categories}, mutation=True
    )


@router.get("/api/codex/status")
async def codex_status():
    return {
        "power": await _system_tool("os_power_plan", {"action": "get"}),
        "dark": await _system_tool("os_dark_mode", {"action": "get"}),
        "firewall": await _system_tool("os_firewall", {"action": "status"}),
        "hibernation": await _system_tool("os_hibernation", {"action": "status"}),
        "adapters": await _system_tool("os_network_adapters", {"action": "list"}),
    }


@router.post("/api/codex/power")
async def codex_power(body: dict = Body(...)):
    return await _system_tool(
        "os_power_plan",
        {"action": "set", "plan": (body or {}).get("plan")},
        mutation=True,
    )


@router.post("/api/codex/dark")
async def codex_dark(body: dict = Body(...)):
    return await _system_tool(
        "os_dark_mode",
        {"action": (body or {}).get("action", "toggle")},
        mutation=True,
    )


@router.post("/api/codex/firewall")
async def codex_firewall(body: dict = Body(...)):
    return await _system_tool(
        "os_firewall",
        {"action": (body or {}).get("action", "status")},
        mutation=True,
    )


@router.post("/api/codex/hibernation")
async def codex_hibernation(body: dict = Body(...)):
    return await _system_tool(
        "os_hibernation",
        {"action": (body or {}).get("action", "status")},
        mutation=True,
    )


@router.post("/api/codex/adapter")
async def codex_adapter(body: dict = Body(...)):
    payload = body or {}
    return await _system_tool(
        "os_network_adapters",
        {
            "action": payload.get("action"),
            "name": payload.get("name"),
        },
        mutation=True,
    )
