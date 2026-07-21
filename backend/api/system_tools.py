"""Adaptateurs HTTP des outils Windows exposés dans les pages système."""

from fastapi import APIRouter, Body

import tools as tool_module


router = APIRouter(tags=["system-tools"])


@router.get("/api/winget/search")
async def winget_search(q: str, source: str | None = None, limit: int = 20):
    args = {"query": q, "limit": limit}
    if source:
        args["source"] = source
    return await tool_module.TOOLS_REGISTRY["winget_search"](args)


@router.get("/api/winget/upgrades")
async def winget_upgrades():
    return await tool_module.TOOLS_REGISTRY["winget_list_upgrades"]({})


@router.get("/api/winget/installed")
async def winget_installed(q: str | None = None):
    return await tool_module.TOOLS_REGISTRY["winget_list_installed"]({"query": q} if q else {})


@router.post("/api/winget/install")
async def winget_install(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["winget_install"]({**(body or {}), "confirmed": True})


@router.post("/api/winget/upgrade")
async def winget_upgrade(body: dict = Body(default={})):
    return await tool_module.TOOLS_REGISTRY["winget_upgrade"]({**(body or {}), "confirmed": True})


@router.post("/api/winget/uninstall")
async def winget_uninstall(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["winget_uninstall"]({**(body or {}), "confirmed": True})


@router.get("/api/pantheon/telemetry")
async def pantheon_telemetry_status():
    return await tool_module.TOOLS_REGISTRY["tweak_telemetry"]({"action": "status"})


@router.post("/api/pantheon/telemetry")
async def pantheon_telemetry_set(body: dict = Body(...)):
    action = (body or {}).get("action", "disable")
    return await tool_module.TOOLS_REGISTRY["tweak_telemetry"]({"action": action, "confirmed": True})


@router.get("/api/pantheon/debloat")
async def pantheon_debloat_list():
    return await tool_module.TOOLS_REGISTRY["tweak_debloat_list"]({})


@router.post("/api/pantheon/debloat/remove")
async def pantheon_debloat_remove(body: dict = Body(...)):
    packages = (body or {}).get("packages") or []
    return await tool_module.TOOLS_REGISTRY["tweak_debloat_remove"](
        {"packages": packages, "confirmed": True}
    )


@router.get("/api/pantheon/network")
async def pantheon_network_status():
    return await tool_module.TOOLS_REGISTRY["tweak_network_harden"]({"action": "status"})


@router.post("/api/pantheon/network/apply")
async def pantheon_network_apply():
    return await tool_module.TOOLS_REGISTRY["tweak_network_harden"](
        {"action": "apply", "confirmed": True}
    )


@router.post("/api/pantheon/restore-point")
async def pantheon_restore_point(body: dict = Body(default={})):
    description = (body or {}).get("description", "Marvin — avant optimisation")
    return await tool_module.TOOLS_REGISTRY["system_restore_point"](
        {"description": description, "confirmed": True}
    )


@router.get("/api/catharsis/scan")
async def catharsis_scan():
    return await tool_module.TOOLS_REGISTRY["catharsis_scan"]({})


@router.post("/api/catharsis/clean")
async def catharsis_clean(body: dict = Body(...)):
    categories = (body or {}).get("categories") or []
    return await tool_module.TOOLS_REGISTRY["catharsis_clean"](
        {"categories": categories, "confirmed": True}
    )


@router.get("/api/codex/status")
async def codex_status():
    registry = tool_module.TOOLS_REGISTRY
    return {
        "power": await registry["os_power_plan"]({"action": "get"}),
        "dark": await registry["os_dark_mode"]({"action": "get"}),
        "firewall": await registry["os_firewall"]({"action": "status"}),
        "hibernation": await registry["os_hibernation"]({"action": "status"}),
        "adapters": await registry["os_network_adapters"]({"action": "list"}),
    }


@router.post("/api/codex/power")
async def codex_power(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["os_power_plan"](
        {"action": "set", "plan": (body or {}).get("plan"), "confirmed": True}
    )


@router.post("/api/codex/dark")
async def codex_dark(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["os_dark_mode"](
        {"action": (body or {}).get("action", "toggle"), "confirmed": True}
    )


@router.post("/api/codex/firewall")
async def codex_firewall(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["os_firewall"](
        {"action": (body or {}).get("action", "status"), "confirmed": True}
    )


@router.post("/api/codex/hibernation")
async def codex_hibernation(body: dict = Body(...)):
    return await tool_module.TOOLS_REGISTRY["os_hibernation"](
        {"action": (body or {}).get("action", "status"), "confirmed": True}
    )


@router.post("/api/codex/adapter")
async def codex_adapter(body: dict = Body(...)):
    payload = body or {}
    return await tool_module.TOOLS_REGISTRY["os_network_adapters"](
        {
            "action": payload.get("action"),
            "name": payload.get("name"),
            "confirmed": True,
        }
    )
