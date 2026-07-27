"""Registre Windows et points de restauration avec sauvegarde et validation."""
from __future__ import annotations

import asyncio
import os
import re as _re
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

async def _missing_tool(_args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "Runner PowerShell non configur?."}

_run_powershell: Tool = _missing_tool

def configure(*, run_powershell: Tool) -> None:
    global _run_powershell
    _run_powershell = run_powershell

def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""

def _registry_path(value: Any) -> str | None:
    path = _text(value)
    if not path or len(path) > 512:
        return None
    if not _re.fullmatch(r"(?:HKLM|HKCU|HKCR|HKU|HKCC):\\[^'\";\r\n]+", path, _re.IGNORECASE):
        return None
    return path

def _registry_name(value: Any) -> str | None:
    name = _text(value)
    if not name or len(name) > 255 or not _re.fullmatch(r"[^'\";\r\n]+", name):
        return None
    return name

def _ps_string(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 32768 or "\x00" in value:
        return None
    return "'" + value.replace("'", "''") + "'"


def _registry_value_expression(value: Any, registry_type: str) -> str | None:
    if registry_type in ("DWord", "QWord"):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        maximum = 0xFFFFFFFF if registry_type == "DWord" else 0x7FFFFFFFFFFFFFFF
        return str(number) if 0 <= number <= maximum else None
    if registry_type in ("String", "ExpandString"):
        return _ps_string(value)
    if registry_type == "MultiString":
        if not isinstance(value, list) or not 1 <= len(value) <= 256:
            return None
        encoded = [_ps_string(item) for item in value]
        return "@(" + ",".join(encoded) + ")" if all(encoded) else None
    if registry_type == "Binary":
        if not isinstance(value, list) or not 1 <= len(value) <= 4096:
            return None
        try:
            octets = [int(item) for item in value]
        except (TypeError, ValueError):
            return None
        return "[byte[]]@(" + ",".join(map(str, octets)) + ")" if all(
            0 <= item <= 255 for item in octets
        ) else None
    return None

_REG_BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "registry_backups")

def _ps_reg_to_native(path: str) -> str:
    """HKLM:\\SOFTWARE\\... → HKLM\\SOFTWARE\\... (format attendu par reg.exe)."""
    p = (path or "").strip()
    for k, v in (("HKLM:", "HKLM"), ("HKCU:", "HKCU"), ("HKCR:", "HKCR"), ("HKU:", "HKU"), ("HKCC:", "HKCC")):
        if p.upper().startswith(k):
            return v + p[len(k):]
    return p.replace(":", "")

async def _reg_backup(ps_path: str) -> str | None:
    """Exporte une clé de registre en .reg (sauvegarde de secours)."""
    import time as _t
    try:
        os.makedirs(_REG_BACKUP_DIR, exist_ok=True)
        native = _ps_reg_to_native(ps_path)
        safe = _re.sub(r"[^A-Za-z0-9]+", "_", native)[:60]
        out = os.path.join(_REG_BACKUP_DIR, f"{safe}_{_t.strftime('%Y%m%d-%H%M%S')}.reg")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        p = await asyncio.to_thread(subprocess.run, ["reg", "export", native, out, "/y"], capture_output=True, text=True,
                           timeout=30, creationflags=flags, encoding="utf-8", errors="replace")
        if p.returncode == 0 and os.path.exists(out):
            return os.path.abspath(out)
    except Exception:
        pass
    return None

async def execute_system_restore_point(args: dict) -> dict:
    """Crée un point de restauration système (filet de sécurité avant optimisation)."""
    desc = _text(args.get("description")) or "Marvin — avant optimisation"
    if len(desc) > 120 or "\x00" in desc:
        return {"error": "Description invalide (120 caractères maximum)."}
    desc_literal = _ps_string(desc)
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"Créer un point de restauration « {desc} » ?"}
    ps = ("try { Enable-ComputerRestore -Drive 'C:\\' -EA SilentlyContinue } catch {};"
          f"Checkpoint-Computer -Description {desc_literal} -RestorePointType 'MODIFY_SETTINGS'; 'OK'")
    r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 120})
    ok = "OK" in (r.get("stdout") or "") and not r.get("error")
    return {"success": ok,
            "message": ("✅ Point de restauration créé." if ok else
                        "❌ Échec — Restauration système désactivée, droits ADMIN manquants, "
                        "ou limite d'1 point / 24 h atteinte."),
            "detail": (r.get("stderr") or r.get("error") or "")[:300]}

async def execute_registry_get(args: dict) -> dict:
    """Lit une valeur (ou toutes les valeurs) d'une clé de registre (lecture seule)."""
    path = _registry_path(args.get("path"))
    raw_name = args.get("name")
    name = _registry_name(raw_name) if raw_name is not None else None
    if not path:
        return {"error": "Paramètre 'path' invalide (ex: HKLM:\\SOFTWARE\\Microsoft\\Windows)."}
    if raw_name is not None and not name:
        return {"error": "Paramètre 'name' invalide."}
    if name:
        ps = f"(Get-ItemProperty -Path '{path}' -Name '{name}' -EA Stop).'{name}'"
    else:
        ps = f"Get-ItemProperty -Path '{path}' -EA Stop | Format-List *"
    r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 20})
    out = (r.get("stdout") or "").strip()
    if r.get("returncode") != 0 or not out or out == "(aucune sortie)":
        return {"success": False, "path": path, "message": "Clé ou valeur introuvable.",
                "detail": (r.get("stderr") or "")[:200]}
    return {"success": True, "path": path, "name": name, "value": out[:1500]}

async def execute_registry_backup(args: dict) -> dict:
    """Exporte une clé de registre dans un fichier .reg de secours."""
    path = _registry_path(args.get("path"))
    if not path:
        return {"error": "Paramètre 'path' invalide."}
    out = await _reg_backup(path)
    return ({"success": True, "backup": out, "message": f"✅ Sauvegarde : {out}"} if out
            else {"success": False, "message": "❌ Export du registre échoué (droits ?)."})

async def execute_registry_set(args: dict) -> dict:
    """Écrit une valeur de registre — SAUVEGARDE AUTO de la clé d'abord + confirmation."""
    path = _registry_path(args.get("path"))
    name = _registry_name(args.get("name"))
    value = args.get("value")
    raw_type = _text(args.get("type")) or "DWord"
    type_map = {
        "dword": "DWord", "qword": "QWord", "string": "String",
        "expandstring": "ExpandString", "multistring": "MultiString", "binary": "Binary",
    }
    rtype = type_map.get(raw_type.lower())
    if not path or not name or value is None:
        return {"error": "Paramètres 'path', 'name' et 'value' valides requis."}
    if not rtype:
        return {"error": "Type de registre invalide."}
    val = _registry_value_expression(value, rtype)
    if val is None:
        return {"error": f"Valeur invalide pour le type {rtype}."}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True,
                "message": f"Modifier le registre {path}\\{name} = {value} ({rtype}) ? "
                           f"(une sauvegarde .reg est faite automatiquement)"}
    backup = await _reg_backup(path)
    ps = (f"if(-not (Test-Path '{path}')){{ New-Item -Path '{path}' -Force | Out-Null }};"
          f"New-ItemProperty -Path '{path}' -Name '{name}' -Value {val} -PropertyType {rtype} -Force | Out-Null; 'OK'")
    r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 30})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "path": path, "name": name, "backup": backup,
            "message": ("✅ Registre modifié (sauvegarde effectuée)." if ok else
                        "❌ Échec — droits ADMINISTRATEUR probablement requis."),
            "detail": (r.get("stderr") or "")[:250]}
