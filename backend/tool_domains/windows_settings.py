"""Param?tres Windows d?claratifs avec confirmation des mutations."""
from __future__ import annotations

import re as _re
from collections.abc import Awaitable, Callable
from typing import Any

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

async def _missing_tool(_args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "D?pendance Windows non configur?e."}

_run_powershell: Tool = _missing_tool
_registry_get: Tool = _missing_tool

def configure(*, run_powershell: Tool, registry_get: Tool) -> None:
    global _run_powershell, _registry_get
    _run_powershell = run_powershell
    _registry_get = registry_get

def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""

def _adapter_name(value: Any) -> str | None:
    name = _text(value)
    if not name or len(name) > 128 or not _re.fullmatch(r"[A-Za-z0-9?-? ._()#\-]+", name):
        return None
    return name

_POWER_PLANS = {
    "balanced":    "381b4222-f694-41f0-9685-ff5bb260df2e",
    "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "powersaver":  "a1841308-3541-4fab-bc81-f71556f20b4a",
}

_DARK_KEY = r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"

async def execute_os_power_plan(args: dict) -> dict:
    """Lit ou change le plan d'alimentation Windows (équilibré / performances / économie)."""
    action = (_text(args.get("action")) or "get").lower()
    if action in ("get", "status"):
        r = await _run_powershell({"script": "powercfg /getactivescheme", "confirmed": True, "timeout": 15})
        out = (r.get("stdout") or "").strip()
        active = "performance" if "8c5e7fda" in out.lower() else "powersaver" if "a1841308" in out.lower() else "balanced" if "381b4222" in out.lower() else "personnalisé"
        return {"success": True, "active_plan": active, "raw": out[:200]}
    if action != "set":
        return {"error": "action attendue : get | set"}
    plan = _text(args.get("plan")).lower()
    if plan not in _POWER_PLANS:
        return {"error": "plan attendu : balanced | performance | powersaver"}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"Activer le plan d'alimentation « {plan} » ?"}
    r = await _run_powershell({"script": f"powercfg /setactive {_POWER_PLANS[plan]}; 'OK'", "confirmed": True, "timeout": 20})
    ok = "OK" in (r.get("stdout") or "") and r.get("returncode") == 0
    return {"success": ok, "plan": plan, "message": (f"✅ Plan « {plan} » activé." if ok else "❌ Échec.")}

async def execute_os_dark_mode(args: dict) -> dict:
    """Lit ou bascule le mode sombre/clair de Windows (apps + système). Sans droits admin."""
    action = (_text(args.get("action")) or "get").lower()
    if action in ("get", "status"):
        k = await _registry_get({"path": _DARK_KEY, "name": "AppsUseLightTheme"})
        light = str(k.get("value", "1")).strip() == "1" if k.get("success") else True
        return {"success": True, "mode": "clair" if light else "sombre"}
    if action not in ("enable", "disable", "dark", "light", "toggle"):
        return {"error": "action : get | dark | light"}
    if action == "toggle":
        cur = await execute_os_dark_mode({"action": "get"})
        action = "light" if cur.get("mode") == "sombre" else "dark"
    val = 0 if action in ("enable", "dark") else 1   # 0 = sombre, 1 = clair
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"Passer Windows en mode {'sombre' if val == 0 else 'clair'} ?"}
    ps = (f"New-ItemProperty -Path '{_DARK_KEY}' -Name AppsUseLightTheme -Value {val} -PropertyType DWord -Force | Out-Null;"
          f"New-ItemProperty -Path '{_DARK_KEY}' -Name SystemUsesLightTheme -Value {val} -PropertyType DWord -Force | Out-Null; 'OK'")
    r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 20})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "mode": "sombre" if val == 0 else "clair",
            "message": (f"✅ Mode {'sombre' if val == 0 else 'clair'} appliqué." if ok else "❌ Échec.")}

async def execute_os_firewall(args: dict) -> dict:
    """Statut / activation / désactivation du pare-feu Windows Defender (tous profils)."""
    action = (_text(args.get("action")) or "status").lower()
    if action in ("status", "get"):
        r = await _run_powershell({"script": "Get-NetFirewallProfile | Select-Object Name,Enabled | Format-Table -HideTableHeaders | Out-String", "confirmed": True, "timeout": 20})
        return {"success": True, "status": (r.get("stdout") or "").strip()[:300]}
    if action not in ("on", "off", "enable", "disable"):
        return {"error": "action : status | on | off"}
    enable = action in ("on", "enable")
    if not args.get("confirmed"):
        warn = "" if enable else " ⚠️ Désactiver le pare-feu réduit votre sécurité."
        return {"requiresConfirmation": True, "message": f"{'Activer' if enable else 'Désactiver'} le pare-feu Windows (tous profils) ?{warn}"}
    ps = f"Set-NetFirewallProfile -All -Enabled {'True' if enable else 'False'}; 'OK'"
    r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 25})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "message": (f"✅ Pare-feu {'activé' if enable else 'désactivé'}." if ok else "❌ Échec — droits ADMIN requis."),
            "detail": (r.get("stderr") or "")[:200]}

async def execute_os_network_adapters(args: dict) -> dict:
    """Liste / active / désactive les cartes réseau."""
    action = (_text(args.get("action")) or "list").lower()
    if action in ("list", "get", "status"):
        r = await _run_powershell({"script": "Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,LinkSpeed | ConvertTo-Json -Compress", "confirmed": True, "timeout": 20})
        import json as _j
        try:
            data = _j.loads((r.get("stdout") or "[]").strip())
            if isinstance(data, dict):
                data = [data]
        except Exception:
            data = []
        return {"success": True, "adapters": data}
    name = _adapter_name(args.get("name"))
    if not name or action not in ("enable", "disable"):
        return {"error": "action : list | enable | disable (+ 'name')"}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"{'Activer' if action == 'enable' else 'Désactiver'} la carte réseau « {name} » ?"}
    verb = "Enable-NetAdapter" if action == "enable" else "Disable-NetAdapter"
    r = await _run_powershell({"script": f"{verb} -Name '{name}' -Confirm:$false; 'OK'", "confirmed": True, "timeout": 25})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "message": (f"✅ Carte « {name} » {'activée' if action == 'enable' else 'désactivée'}." if ok else "❌ Échec — droits ADMIN requis."),
            "detail": (r.get("stderr") or "")[:200]}

async def execute_os_hibernation(args: dict) -> dict:
    """Statut / activation / désactivation de l'hibernation (libère hiberfil.sys)."""
    action = (_text(args.get("action")) or "status").lower()
    if action in ("status", "get"):
        r = await _run_powershell({"script": "powercfg /a", "confirmed": True, "timeout": 15})
        out = (r.get("stdout") or "")
        on = "hibernation" in out.lower() and "non disponible" not in out.lower().split("hibernation")[-1][:60]
        return {"success": True, "raw": out.strip()[:400]}
    if action not in ("on", "off", "enable", "disable"):
        return {"error": "action : status | on | off"}
    enable = action in ("on", "enable")
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"{'Activer' if enable else 'Désactiver'} l'hibernation ? {'(désactiver libère plusieurs Go : hiberfil.sys)' if not enable else ''}"}
    r = await _run_powershell({"script": f"powercfg /hibernate {'on' if enable else 'off'}; 'OK'", "confirmed": True, "timeout": 20})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "message": (f"✅ Hibernation {'activée' if enable else 'désactivée'}." if ok else "❌ Échec — droits ADMIN requis.")}
