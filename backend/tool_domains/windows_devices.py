"""Périphériques Windows : imprimantes, USB, Bluetooth (v2.524).

Constat d'audit : 0 outil imprimante/USB/Bluetooth dans tout le projet, alors que ce
sont des besoins quotidiens réels pour un technicien IT. Comblé ici avec le même
patron que `windows_settings.py` : lecture via WMI/PowerShell sans confirmation,
mutation avec confirmation explicite. Aucune nouvelle dépendance Python — PowerShell
suffit, cohérent avec le reste du domaine Windows.
"""
from __future__ import annotations

import json as _json
import re as _re
from collections.abc import Awaitable, Callable
from typing import Any

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def _missing_tool(_args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "Dépendance PowerShell non configurée."}


_run_powershell: Tool = _missing_tool


def configure(*, run_powershell: Tool) -> None:
    global _run_powershell
    _run_powershell = run_powershell


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_name(value: Any) -> str | None:
    """Nom d'imprimante/périphérique : bloque l'injection dans un script PowerShell."""
    name = _text(value)
    if not name or len(name) > 128 or not _re.fullmatch(r"[\w\s._()\-À-ÿ]+", name):
        return None
    return name


def _parse_json_array(stdout: str) -> list[dict[str, Any]]:
    try:
        data = _json.loads((stdout or "[]").strip() or "[]")
    except Exception:
        return []
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []


async def execute_pc_printer_list(args: dict) -> dict:
    """Liste les imprimantes installées : nom, statut, pilote, si c'est la défaut."""
    r = await _run_powershell({
        "script": (
            "Get-Printer | Select-Object Name,DriverName,PrinterStatus,Default,Shared "
            "| ConvertTo-Json -Compress"
        ),
        "confirmed": True,
        "timeout": 20,
    })
    printers = _parse_json_array(r.get("stdout") or "")
    if not printers and r.get("returncode") != 0:
        return {"error": f"Lecture des imprimantes impossible : {(r.get('stderr') or '')[:200]}"}
    return {"success": True, "printers": printers, "count": len(printers)}


async def execute_pc_printer_set_default(args: dict) -> dict:
    """Définit l'imprimante par défaut."""
    name = _safe_name(args.get("name"))
    if not name:
        return {"error": "Paramètre 'name' requis (nom exact de l'imprimante, voir pc_printer_list)."}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"Définir « {name} » comme imprimante par défaut ?"}
    r = await _run_powershell({
        "script": f"(Get-WmiObject -Class Win32_Printer -Filter \"Name='{name}'\").SetDefaultPrinter() | Out-Null; 'OK'",
        "confirmed": True,
        "timeout": 20,
    })
    ok = "OK" in (r.get("stdout") or "")
    return {
        "success": ok,
        "message": (f"✅ « {name} » définie par défaut." if ok else "❌ Échec — imprimante introuvable ou droits insuffisants."),
        "detail": (r.get("stderr") or "")[:200],
    }


async def execute_pc_usb_list(args: dict) -> dict:
    """Liste les périphériques USB actuellement connectés (WMI PnP)."""
    r = await _run_powershell({
        "script": (
            "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB*' } "
            "| Select-Object FriendlyName,Class,Status "
            "| ConvertTo-Json -Compress"
        ),
        "confirmed": True,
        "timeout": 20,
    })
    devices = _parse_json_array(r.get("stdout") or "")
    return {"success": True, "devices": devices, "count": len(devices)}


async def execute_pc_bluetooth_status(args: dict) -> dict:
    """Statut du radio Bluetooth et périphériques appairés."""
    r = await _run_powershell({
        "script": (
            "$radio = Get-PnpDevice -Class Bluetooth -PresentOnly "
            "| Select-Object FriendlyName,Status; "
            "$paired = Get-PnpDevice -PresentOnly "
            "| Where-Object { $_.InstanceId -like 'BTHENUM*' } "
            "| Select-Object FriendlyName,Status; "
            "@{radios=$radio; paired=$paired} | ConvertTo-Json -Compress -Depth 4"
        ),
        "confirmed": True,
        "timeout": 20,
    })
    try:
        data = _json.loads((r.get("stdout") or "{}").strip() or "{}")
    except Exception:
        data = {}
    radios = data.get("radios") or []
    paired = data.get("paired") or []
    if isinstance(radios, dict):
        radios = [radios]
    if isinstance(paired, dict):
        paired = [paired]
    return {
        "success": True,
        "radios": radios,
        "available": bool(radios),
        "paired_devices": paired,
    }
