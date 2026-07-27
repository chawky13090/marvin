"""Tweaks Windows r?versibles avec catalogue born? et confirmations."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
Backup = Callable[[str], Awaitable[str | None]]

async def _missing_tool(_args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "D?pendance Windows non configur?e."}

async def _missing_backup(_path: str) -> str | None:
    return None

_run_powershell: Tool = _missing_tool
_registry_get: Tool = _missing_tool
_reg_backup: Backup = _missing_backup

def configure(*, run_powershell: Tool, registry_get: Tool, reg_backup: Backup) -> None:
    global _run_powershell, _registry_get, _reg_backup
    _run_powershell = run_powershell
    _registry_get = registry_get
    _reg_backup = reg_backup

def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""

_TELEMETRY_KEY = r"HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection"

_BLOATWARE = [
    "Microsoft.BingNews", "Microsoft.BingWeather", "Microsoft.GamingApp", "Microsoft.GetHelp",
    "Microsoft.Getstarted", "Microsoft.MicrosoftSolitaireCollection", "Microsoft.People",
    "Microsoft.PowerAutomateDesktop", "Microsoft.Todos", "Microsoft.WindowsFeedbackHub",
    "Microsoft.WindowsMaps", "Microsoft.Xbox.TCUI", "Microsoft.XboxGameOverlay",
    "Microsoft.XboxGamingOverlay", "Microsoft.XboxIdentityProvider", "Microsoft.XboxSpeechToTextOverlay",
    "Microsoft.ZuneMusic", "Microsoft.ZuneVideo", "Microsoft.YourPhone", "Clipchamp.Clipchamp",
    "Microsoft.549981C3F5F10", "MicrosoftTeams", "Microsoft.MicrosoftStickyNotes",
]

async def execute_tweak_telemetry(args: dict) -> dict:
    """Statut / désactivation / réactivation de la télémétrie Windows (DiagTrack + AllowTelemetry)."""
    action = (_text(args.get("action")) or "status").lower()
    if action in ("status", "query", "get"):
        svc = await _run_powershell({"script": "(Get-Service DiagTrack -EA SilentlyContinue).Status",
                                               "confirmed": True, "timeout": 15})
        key = await _registry_get({"path": _TELEMETRY_KEY, "name": "AllowTelemetry"})
        return {"success": True, "action": "status",
                "diagtrack": (svc.get("stdout") or "").strip() or "inconnu",
                "allow_telemetry": (key.get("value") if key.get("success") else "non défini (défaut : activé)")}
    if action not in ("disable", "enable"):
        return {"error": "action attendue : status | disable | enable"}
    if not args.get("confirmed"):
        verb = "Désactiver" if action == "disable" else "Réactiver"
        return {"requiresConfirmation": True,
                "message": f"{verb} la télémétrie Windows (service DiagTrack + clé AllowTelemetry) ? "
                           f"(sauvegarde auto, totalement réversible)"}
    backup = await _reg_backup(_TELEMETRY_KEY)
    if action == "disable":
        ps = (f"if(-not (Test-Path '{_TELEMETRY_KEY}')){{New-Item -Path '{_TELEMETRY_KEY}' -Force|Out-Null}};"
              f"New-ItemProperty -Path '{_TELEMETRY_KEY}' -Name AllowTelemetry -Value 0 -PropertyType DWord -Force|Out-Null;"
              "Stop-Service DiagTrack -Force -EA SilentlyContinue;"
              "Set-Service DiagTrack -StartupType Disabled -EA SilentlyContinue;"
              "Stop-Service dmwappushservice -Force -EA SilentlyContinue;"
              "Set-Service dmwappushservice -StartupType Disabled -EA SilentlyContinue; 'OK'")
    else:
        ps = (f"New-ItemProperty -Path '{_TELEMETRY_KEY}' -Name AllowTelemetry -Value 1 -PropertyType DWord -Force -EA SilentlyContinue|Out-Null;"
              "Set-Service DiagTrack -StartupType Automatic -EA SilentlyContinue; Start-Service DiagTrack -EA SilentlyContinue;"
              "Set-Service dmwappushservice -StartupType Manual -EA SilentlyContinue; 'OK'")
    r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 45})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "action": action, "backup": backup,
            "message": (f"✅ Télémétrie {'désactivée' if action == 'disable' else 'réactivée'}." if ok else
                        "❌ Échec — droits ADMINISTRATEUR requis."),
            "detail": (r.get("stderr") or "")[:250]}

async def execute_tweak_debloat_list(args: dict) -> dict:
    """Liste les bloatwares d'usine (UWP) présents et désinstallables (lecture seule)."""
    r = await _run_powershell({"script": "Get-AppxPackage | Select-Object -ExpandProperty Name",
                                         "confirmed": True, "timeout": 45})
    installed = [i.strip() for i in (r.get("stdout") or "").splitlines() if i.strip()]
    inst_lc = {i.lower() for i in installed}
    present = [b for b in _BLOATWARE if b.lower() in inst_lc or any(i.startswith(b.lower()) for i in inst_lc)]
    return {"success": True, "removable": present, "count": len(present),
            "note": "Applications d'usine non essentielles détectées (réinstallables via le Microsoft Store)."}

async def execute_tweak_debloat_remove(args: dict) -> dict:
    """Désinstalle des applications UWP (bloatware). Nécessite confirmation."""
    raw_packages = args.get("packages")
    if raw_packages is None:
        raw_packages = [args["package"]] if args.get("package") else []
    if not isinstance(raw_packages, list):
        return {"error": "Paramètre 'packages' invalide : liste attendue."}
    allowed = {package.lower(): package for package in _BLOATWARE}
    pkgs = []
    for package in raw_packages[:30]:
        canonical = allowed.get(_text(package).lower())
        if canonical and canonical not in pkgs:
            pkgs.append(canonical)
    if not pkgs:
        return {"error": "Aucun package autorisé dans le catalogue de débloat."}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True,
                "message": f"Désinstaller {len(pkgs)} application(s) : {', '.join(pkgs)} ?"}
    removed, failed = [], []
    for p in pkgs:
        ps = f"Get-AppxPackage -Name '{p}*' | Remove-AppxPackage -EA SilentlyContinue; 'done'"
        r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 60})
        (removed if r.get("returncode") == 0 else failed).append(p)
    return {"success": bool(removed) or not failed, "removed": removed, "failed": failed,
            "message": f"✅ {len(removed)} application(s) retirée(s)" + (f", {len(failed)} échec(s)" if failed else "")}

async def execute_tweak_network_harden(args: dict) -> dict:
    """Statut / application d'optimisations réseau légères (cache DNS, auto-tuning TCP)."""
    action = (_text(args.get("action")) or "status").lower()
    if action in ("status", "query", "get"):
        ps = ("Get-DnsClientCache -EA SilentlyContinue | Measure-Object | "
              "ForEach-Object { 'Entrees cache DNS: ' + $_.Count };"
              "netsh int tcp show global")
        r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 20})
        return {"success": True, "action": "status", "output": (r.get("stdout") or "").strip()[:800]}
    if action != "apply":
        return {"error": "action attendue : status | apply"}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True,
                "message": "Appliquer un durcissement réseau léger (vider le cache DNS + ajuster l'auto-tuning TCP) ?"}
    ps = ("Clear-DnsClientCache -EA SilentlyContinue;"
          "netsh int tcp set global autotuninglevel=normal | Out-Null;"
          "netsh int tcp set heuristics disabled | Out-Null; 'OK'")
    r = await _run_powershell({"script": ps, "confirmed": True, "timeout": 40})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "action": "apply",
            "message": ("✅ Réseau optimisé (cache DNS vidé, TCP ajusté)." if ok else
                        "❌ Échec — droits ADMINISTRATEUR requis pour netsh."),
            "detail": (r.get("stderr") or "")[:200]}
