"""Nettoyage Catharsis born? ? un catalogue interne de caches Windows."""
from __future__ import annotations

import json as _json
from collections.abc import Awaitable, Callable
from typing import Any

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

async def _missing_tool(_args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "Runner PowerShell non configur?."}

_run_powershell: Tool = _missing_tool

def configure(*, run_powershell: Tool) -> None:
    global _run_powershell
    _run_powershell = run_powershell

_CLEAN_CATS = {
    # ── Windows ──
    "temp_user":     ("Fichiers temporaires (utilisateur)", [r"$env:TEMP\*"], "Windows"),
    "temp_windows":  ("Fichiers temporaires (Windows)",     [r"C:\Windows\Temp\*"], "Windows"),
    "thumbnails":    ("Cache des vignettes",                [r"$env:LOCALAPPDATA\Microsoft\Windows\Explorer\thumbcache_*.db"], "Windows"),
    "prefetch":      ("Prefetch (préchargement)",           [r"C:\Windows\Prefetch\*"], "Windows"),
    "recent":        ("Documents récents (raccourcis)",     [r"$env:APPDATA\Microsoft\Windows\Recent\*"], "Windows"),
    "error_reports": ("Rapports d'erreurs (WER)",           [r"$env:LOCALAPPDATA\Microsoft\Windows\WER\*", r"$env:ProgramData\Microsoft\Windows\WER\*"], "Windows"),
    "delivery_opt":  ("Cache Windows Update",               [r"C:\Windows\SoftwareDistribution\DeliveryOptimization\*"], "Windows"),
    # ── Système ──
    "crash_dumps":   ("Rapports de plantage (.dmp)",        [r"C:\Windows\Minidump\*", r"$env:LOCALAPPDATA\CrashDumps\*"], "Système"),
    "dx_cache":      ("Cache shaders DirectX / GPU",        [r"$env:LOCALAPPDATA\D3DSCache\*", r"$env:LOCALAPPDATA\NVIDIA\DXCache\*"], "Système"),
    "font_cache":    ("Cache des polices (logs)",           [r"$env:LOCALAPPDATA\FontCache\*"], "Système"),
    # ── Navigateurs ──
    "edge_cache":    ("Cache Microsoft Edge",               [r"$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache\*"], "Navigateurs"),
    "chrome_cache":  ("Cache Google Chrome",                [r"$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Cache\*"], "Navigateurs"),
    "firefox_cache": ("Cache Mozilla Firefox",              [r"$env:LOCALAPPDATA\Mozilla\Firefox\Profiles\*\cache2\*"], "Navigateurs"),
}

_RECYCLE_GROUP = "Windows"

async def execute_catharsis_scan(args: dict) -> dict:
    """Analyse l'espace récupérable par catégorie (NE SUPPRIME RIEN)."""
    lines = ["$o=@{}"]
    for cid, (_label, paths, _grp) in _CLEAN_CATS.items():
        # double quotes → PowerShell développe bien $env:TEMP, $env:LOCALAPPDATA, etc.
        ps_paths = ",".join('"' + p + '"' for p in paths)
        lines.append(
            f"$s=0; foreach($p in @({ps_paths})){{ "
            f"Get-ChildItem -Path $p -Recurse -Force -EA SilentlyContinue | "
            f"ForEach-Object {{ $s += $_.Length }} }}; $o['{cid}']=[int64]$s")
    lines.append("try{ $rb=((New-Object -ComObject Shell.Application).Namespace(10).Items() | "
                 "ForEach-Object { $_.Size } | Measure-Object -Sum).Sum; $o['recycle_bin']=[int64]$rb }"
                 "catch{ $o['recycle_bin']=0 }")
    lines.append("$o | ConvertTo-Json -Compress")
    r = await _run_powershell({"script": ";".join(lines), "confirmed": True, "timeout": 150})
    try:
        data = _json.loads((r.get("stdout") or "{}").strip())
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    labels = {cid: lbl for cid, (lbl, _p, _g) in _CLEAN_CATS.items()}
    groups = {cid: g for cid, (_l, _p, g) in _CLEAN_CATS.items()}
    labels["recycle_bin"] = "Corbeille"; groups["recycle_bin"] = _RECYCLE_GROUP
    cats, total = [], 0
    for cid, by in (data or {}).items():
        if cid not in _CLEAN_CATS and cid != "recycle_bin":
            continue
        try:
            by = max(0, int(by or 0))
        except (TypeError, ValueError):
            by = 0
        total += by
        cats.append({"id": cid, "label": labels.get(cid, cid), "group": groups.get(cid, "Autres"),
                     "bytes": by, "mb": round(by / 1048576, 1)})
    cats.sort(key=lambda c: -c["bytes"])
    return {"success": True, "categories": cats, "total_mb": round(total / 1048576, 1)}

async def execute_catharsis_clean(args: dict) -> dict:
    """Purge les catégories choisies (ids issus de catharsis_scan). Demande confirmation."""
    raw_categories = args.get("categories")
    if not isinstance(raw_categories, list):
        return {"error": "Paramètre 'categories' invalide : liste attendue."}
    cats = []
    for category in raw_categories:
        if (
            isinstance(category, str)
            and (category in _CLEAN_CATS or category == "recycle_bin")
            and category not in cats
        ):
            cats.append(category)
    if not cats:
        return {"error": "Paramètre 'categories' requis (ids depuis catharsis_scan)."}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True,
                "message": f"Vider {len(cats)} catégorie(s) : {', '.join(cats)} ? "
                           f"(suppression définitive de fichiers temporaires/caches)"}
    lines = []
    for cid in cats:
        if cid == "recycle_bin":
            lines.append("Clear-RecycleBin -Force -EA SilentlyContinue")
            continue
        for p in _CLEAN_CATS[cid][1]:
            lines.append(f'Get-ChildItem -Path "{p}" -Force -EA SilentlyContinue | '
                         f'Remove-Item -Recurse -Force -EA SilentlyContinue')
    lines.append("'OK'")
    r = await _run_powershell({"script": ";".join(lines), "confirmed": True, "timeout": 240})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "cleaned": cats,
            "message": (f"✅ {len(cats)} catégorie(s) nettoyée(s)." if ok else
                        "⚠️ Nettoyage partiel (certains fichiers étaient verrouillés/en usage).")}
