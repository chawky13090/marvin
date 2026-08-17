"""Domaine diagnostic PC : mat?riel, sant?, pilotes et fiabilit? observ?e."""
from __future__ import annotations
import asyncio
import datetime as _dt
import json
import json as _j
import socket as _sock
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any
import psutil
import database as db

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
async def _missing_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "D?pendance diagnostic non configur?e."}
_run_powershell: Tool = _missing_tool
_web_search: Tool = _missing_tool
def configure(*, run_powershell: Tool, web_search: Tool) -> None:
    global _run_powershell, _web_search
    _run_powershell = run_powershell
    _web_search = web_search


def _hw_vendor_key(value: str) -> str:
    s = str(value or "").strip().lower()
    aliases = {
        "hewlett-packard": "hp", "hp inc.": "hp", "hp": "hp",
        "dell inc.": "dell", "dell": "dell",
        "lenovo": "lenovo",
        "asus": "asus", "asustek computer inc.": "asus", "asustek": "asus",
        "acer": "acer",
        "microsoft corporation": "microsoft", "microsoft": "microsoft",
        "micro-star international co., ltd.": "msi", "micro-star international": "msi", "msi": "msi",
        "gigabyte technology co., ltd.": "gigabyte", "gigabyte": "gigabyte",
        "asrock": "asrock",
        "intel": "intel",
        "advanced micro devices": "amd", "amd": "amd",
        "nvidia": "nvidia",
    }
    for needle, key in aliases.items():
        if needle in s:
            return key
    return s.split()[0] if s else ""


def _hw_link(label: str, url: str, kind: str = "support", confidence: str = "official") -> dict:
    return {"label": label, "url": url, "kind": kind, "confidence": confidence}


def _hw_manufacturer_links(manufacturer: str, model: str = "", serial: str = "") -> list:
    from urllib.parse import quote_plus
    key = _hw_vendor_key(manufacturer)
    q_model, q_serial = quote_plus(model or ""), quote_plus(serial or "")
    links = []
    if key == "dell":
        links.append(_hw_link("Dell Support", f"https://www.dell.com/support/home/fr-fr/product-support/servicetag/{q_serial}/overview" if serial else "https://www.dell.com/support/home/fr-fr"))
        links.append(_hw_link("Dell Pilotes et diagnostics", "https://www.dell.com/support/home/fr-fr?app=drivers"))
    elif key == "hp":
        links.append(_hw_link("HP Support", "https://support.hp.com/fr-fr"))
        links.append(_hw_link("HP Pilotes", f"https://support.hp.com/fr-fr/drivers/selfservice/{q_model}" if model else "https://support.hp.com/fr-fr/drivers"))
    elif key == "lenovo":
        links.append(_hw_link("Lenovo PC Support", "https://pcsupport.lenovo.com/fr/fr"))
        if serial:
            links.append(_hw_link("Lenovo recherche par n° de série", f"https://pcsupport.lenovo.com/fr/fr/search?query={q_serial}"))
    elif key == "asus":
        links.append(_hw_link("ASUS Support", "https://www.asus.com/fr/support/"))
        if model:
            links.append(_hw_link("ASUS recherche support modèle", f"https://www.asus.com/fr/support/search-result?keyword={q_model}", confidence="official-search"))
    elif key == "acer":
        links.append(_hw_link("Acer Support", "https://www.acer.com/fr-fr/support"))
    elif key == "microsoft":
        links.append(_hw_link("Microsoft Surface Support", "https://support.microsoft.com/fr-fr/surface"))
    elif key == "msi":
        links.append(_hw_link("MSI Support", "https://fr.msi.com/support"))
        if model:
            links.append(_hw_link("MSI recherche support modèle", f"https://fr.msi.com/search/{q_model}", confidence="official-search"))
    elif key == "gigabyte":
        links.append(_hw_link("GIGABYTE Support", "https://www.gigabyte.com/fr/Support"))
        if model:
            links.append(_hw_link("GIGABYTE recherche modèle", f"https://www.gigabyte.com/fr/Search?kw={q_model}", confidence="official-search"))
    elif key == "asrock":
        links.append(_hw_link("ASRock Support", "https://www.asrock.com/support/index.fr.asp"))
    return links


def _hw_component_links(kind: str, name: str, manufacturer: str = "") -> list:
    from urllib.parse import quote_plus
    text = f"{manufacturer} {name}".strip()
    key = _hw_vendor_key(text)
    q = quote_plus(name or "")
    links = []
    low = text.lower()
    if kind == "cpu":
        if "intel" in low:
            links.append(_hw_link("Intel ARK / recherche CPU", f"https://www.intel.com/content/www/us/en/search.html?ws=text#q={q}", "specs", "official-search"))
            links.append(_hw_link("Intel Driver & Support Assistant", "https://www.intel.com/content/www/fr/fr/support/detect.html", "drivers"))
        elif "amd" in low or "ryzen" in low:
            links.append(_hw_link("AMD Support CPU", f"https://www.amd.com/fr/search?keyword={q}", "specs", "official-search"))
            links.append(_hw_link("AMD Auto-Detect Drivers", "https://www.amd.com/fr/support/download/drivers.html", "drivers"))
    elif kind == "gpu":
        if key == "nvidia" or "geforce" in low or "rtx" in low or "gtx" in low:
            links.append(_hw_link("NVIDIA Pilotes", "https://www.nvidia.com/fr-fr/geforce/drivers/", "drivers"))
            links.append(_hw_link("NVIDIA recherche", f"https://www.nvidia.com/fr-fr/search/?q={q}", "specs", "official-search"))
        elif key == "amd" or "radeon" in low:
            links.append(_hw_link("AMD Radeon Pilotes", "https://www.amd.com/fr/support/download/drivers.html", "drivers"))
        elif key == "intel" or "iris" in low or "uhd graphics" in low:
            links.append(_hw_link("Intel Graphics Pilotes", "https://www.intel.com/content/www/fr/fr/support/products/80939/graphics.html", "drivers"))
    elif kind == "motherboard":
        links.extend(_hw_manufacturer_links(manufacturer, name))
    elif kind == "disk":
        if "samsung" in low:
            links.append(_hw_link("Samsung Memory & Storage Support", "https://semiconductor.samsung.com/consumer-storage/support/"))
        elif "western digital" in low or " wd " in f" {low} ":
            links.append(_hw_link("Western Digital Support", "https://support-fr.wd.com/"))
        elif "seagate" in low:
            links.append(_hw_link("Seagate Support", "https://www.seagate.com/fr/fr/support/"))
        elif "crucial" in low or "micron" in low:
            links.append(_hw_link("Crucial Support", "https://www.crucial.fr/support"))
    return links


def _hw_bytes(n) -> str:
    if not n:
        return "0 B"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def execute_pc_hardware_specs(args: dict) -> dict:
    """Inventaire matériel complet (fabricant/modèle/n° série, CPU, RAM, disques, GPU,
    cartes réseau) + liens officiels support/pilotes selon le fabricant détecté."""
    script = (
        "$cs = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,SystemType,TotalPhysicalMemory; "
        "$csp = Get-CimInstance Win32_ComputerSystemProduct | Select-Object Name,Vendor,Version,IdentifyingNumber,UUID; "
        "$bb = Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product,Version,SerialNumber; "
        "$bios = Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,SerialNumber,ReleaseDate; "
        "$cpu = Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,L2CacheSize,L3CacheSize,SocketDesignation; "
        "$ram = Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer,PartNumber,SerialNumber,Capacity,Speed,ConfiguredClockSpeed,DeviceLocator,BankLabel; "
        "$disks = Get-CimInstance Win32_DiskDrive | Select-Object Model,Manufacturer,SerialNumber,Size,MediaType,InterfaceType,FirmwareRevision,Status; "
        "$gpu = Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion,VideoProcessor,PNPDeviceID; "
        "$net = Get-CimInstance Win32_NetworkAdapter | Where-Object {$_.PhysicalAdapter -eq $true} | Select-Object Name,Manufacturer,MACAddress,Speed,NetConnectionStatus; "
        "[pscustomobject]@{computer=$cs; product=$csp; baseboard=$bb; bios=$bios; cpu=$cpu; ram=$ram; disks=$disks; gpu=$gpu; network=$net} | ConvertTo-Json -Depth 4 -Compress"
    )
    r = await _run_powershell({"script": script, "confirmed": True, "timeout": 40})
    import json as _j
    try:
        raw = _j.loads((r.get("stdout") or "{}").strip())
    except Exception as e:
        return {"error": f"Impossible de lire l'inventaire matériel : {e}", "raw_output": (r.get("stdout") or "")[:500]}
    if not isinstance(raw, dict):
        return {"error": "Réponse PowerShell inattendue.", "raw_output": str(raw)[:500]}

    def _as_list(v):
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def _clean(v) -> str:
        return str(v or "").strip()

    computer = raw.get("computer") or {}
    product = raw.get("product") or {}
    baseboard = raw.get("baseboard") or {}
    bios = raw.get("bios") or {}
    manufacturer = _clean(computer.get("Manufacturer") or product.get("Vendor") or baseboard.get("Manufacturer"))
    model = _clean(computer.get("Model") or product.get("Name") or baseboard.get("Product"))
    serial = _clean(product.get("IdentifyingNumber") or bios.get("SerialNumber") or baseboard.get("SerialNumber"))
    generic = {"system manufacturer", "system product name", "to be filled by o.e.m.", "default string", "system serial number"}
    if manufacturer.lower() in generic:
        manufacturer = _clean(baseboard.get("Manufacturer") or product.get("Vendor"))
    if model.lower() in generic:
        model = _clean(baseboard.get("Product") or product.get("Name"))
    if serial.lower() in generic:
        serial = _clean(baseboard.get("SerialNumber") or bios.get("SerialNumber"))

    cpus = _as_list(raw.get("cpu"))
    gpus = _as_list(raw.get("gpu"))
    disks = _as_list(raw.get("disks"))
    ram_modules = _as_list(raw.get("ram"))
    network = _as_list(raw.get("network"))
    total_ram = sum(int(x.get("Capacity") or 0) for x in ram_modules if isinstance(x, dict))

    links = []
    links.extend(_hw_manufacturer_links(manufacturer, model, serial))
    links.extend(_hw_manufacturer_links(baseboard.get("Manufacturer", ""), baseboard.get("Product", "")))
    for c in cpus:
        if isinstance(c, dict):
            links.extend(_hw_component_links("cpu", c.get("Name", ""), c.get("Manufacturer", "")))
    for g in gpus:
        if isinstance(g, dict):
            links.extend(_hw_component_links("gpu", g.get("Name", ""), g.get("VideoProcessor", "")))
    for d in disks:
        if isinstance(d, dict):
            links.extend(_hw_component_links("disk", d.get("Model", ""), d.get("Manufacturer", "")))
    seen, deduped = set(), []
    for link in links:
        u = link.get("url")
        if u and u not in seen:
            seen.add(u)
            deduped.append(link)

    import socket as _sock
    return {
        "success": True,
        "host": _sock.gethostname(),
        "summary": {
            "manufacturer": manufacturer, "model": model, "serial": serial,
            "cpu": _clean((cpus[0] or {}).get("Name")) if cpus else "",
            "gpu": [_clean(g.get("Name")) for g in gpus if isinstance(g, dict) and g.get("Name")],
            "ram_total_human": _hw_bytes(total_ram) if total_ram else _hw_bytes(psutil.virtual_memory().total),
            "disk_count": len(disks),
            "network_adapter_count": len(network),
        },
        "official_links": deduped,
        "components": {
            "cpu": cpus,
            "memory": {"total_human": _hw_bytes(total_ram or psutil.virtual_memory().total), "modules": ram_modules},
            "disks": disks, "gpu": gpus, "network": network,
        },
    }


async def execute_pc_gpu_status(args: dict) -> dict:
    """État du GPU utilisé pour l'IA locale (vidéo…) : marque, VRAM, backend de calcul
    (CUDA NVIDIA / DirectML AMD-Intel / CPU). Détection à rafraîchissement automatique
    (20s) — utilise refresh=true pour forcer une redétection immédiate après un
    changement de carte graphique (utile si tu testes plusieurs cartes)."""
    import local_video as _lv
    force = bool(args.get("refresh", False))
    info = _lv.refresh_device_info() if force else _lv.get_device_info()
    msg = f"{info['device_name']} ({info['vendor'].upper()}) — {info['vram_gb']} Go VRAM — calcul via {info['backend']}"
    if info["backend"] == "cpu":
        msg += " (aucun GPU utilisable détecté, tout tourne sur CPU — lent)"
    elif info["vendor"] == "amd" and not info.get("amd_compute_native"):
        msg += " — carte AMD détectée mais pas de backend de calcul (DirectML indisponible dans cet environnement Python) → génération vidéo locale désactivée"
    return {"success": True, "refreshed": force, "message": msg, **info}


async def execute_pc_hardware_temps(args: dict) -> dict:
    """Températures matérielles RÉELLES (CPU via capteur ACPI si exposé par la carte mère, GPU
    NVIDIA via nvidia-smi). Contrairement à une estimation, ceci lit un vrai capteur — si aucun
    n'est accessible (fréquent sur cartes mères desktop, l'ACPI thermal zone n'est souvent
    exposée que sur les portables), le renvoie explicitement plutôt que de deviner. À utiliser
    AVANT d'affirmer quoi que ce soit sur une éventuelle surchauffe."""
    out = {"success": True, "cpu_temp_c": None, "cpu_temp_available": False,
           "gpu_temp_c": None, "gpu_temp_available": False, "warnings": []}
    try:
        result = await _run_powershell({
            "script": (
                "try { "
                "$t = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop; "
                "if ($t) { $c = [math]::Round((($t[0].CurrentTemperature) / 10.0) - 273.15, 1); "
                "@{available=$true; temp=$c} | ConvertTo-Json -Compress } "
                "else { @{available=$false} | ConvertTo-Json -Compress } "
                "} catch { @{available=$false} | ConvertTo-Json -Compress }"
            ),
            "confirmed": True, "timeout": 10,
        })
        if not result.get("error") and result.get("returncode") == 0:
            data = json.loads(result.get("stdout", "{}") or "{}")
            if data.get("available"):
                out["cpu_temp_c"] = data.get("temp")
                out["cpu_temp_available"] = True
    except Exception:
        pass
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
        if lines and lines[0].strip().lstrip("-").isdigit():
            out["gpu_temp_c"] = int(lines[0].strip())
            out["gpu_temp_available"] = True
    except Exception:
        pass
    if out["cpu_temp_available"] and out["cpu_temp_c"] and out["cpu_temp_c"] >= 85:
        out["warnings"].append(f"⚠️ Température CPU élevée : {out['cpu_temp_c']}°C")
    if out["gpu_temp_available"] and out["gpu_temp_c"] and out["gpu_temp_c"] >= 83:
        out["warnings"].append(f"⚠️ Température GPU élevée : {out['gpu_temp_c']}°C")
    if not out["cpu_temp_available"] and not out["gpu_temp_available"]:
        out["message"] = ("Aucun capteur de température accessible sur cette machine (courant "
                           "sur les cartes mères desktop) — ne pas affirmer d'état thermique "
                           "sans données réelles.")
    return out


async def execute_pc_disk_smart_health(args: dict) -> dict:
    """Santé RÉELLE des disques via les compteurs de fiabilité Windows Storage Management
    (équivalent S.M.A.R.T. : erreurs de lecture non corrigées, usure SSD, heures de
    fonctionnement) — bien plus profond que le simple statut 'Healthy' de win_disk_info, qui ne
    détecte qu'une panne DÉJÀ imminente déclarée par le firmware, pas l'usure progressive."""
    try:
        result = await _run_powershell({
            "script": (
                "Get-PhysicalDisk | ForEach-Object { "
                "$d = $_; try { $r = $d | Get-StorageReliabilityCounter -ErrorAction Stop } catch { $r = $null }; "
                "[PSCustomObject]@{ "
                "FriendlyName=$d.FriendlyName; MediaType=$d.MediaType.ToString(); "
                "HealthStatus=$d.HealthStatus.ToString(); OperationalStatus=($d.OperationalStatus -join ','); "
                "Wear=$r.Wear; Temperature=$r.Temperature; "
                "ReadErrorsTotal=$r.ReadErrorsTotal; ReadErrorsUncorrected=$r.ReadErrorsUncorrected; "
                "PowerOnHours=$r.PowerOnHours } "
                "} | ConvertTo-Json -Depth 2 -Compress"
            ),
            "confirmed": True, "timeout": 20,
        })
        if result.get("error") or result.get("returncode") != 0:
            return {"error": result.get("error") or result.get("stderr") or "Échec PowerShell"}
        data = json.loads(result.get("stdout", "[]") or "[]")
        if isinstance(data, dict):
            data = [data]
        warnings = []
        for d in data:
            wear = d.get("Wear")
            if isinstance(wear, (int, float)) and wear >= 80:
                warnings.append(f"⚠️ {d.get('FriendlyName')} : usure SSD à {wear}% — remplacement à prévoir")
            uncorrected = d.get("ReadErrorsUncorrected")
            if isinstance(uncorrected, (int, float)) and uncorrected > 0:
                warnings.append(f"🔴 {d.get('FriendlyName')} : {uncorrected} erreurs de lecture NON corrigées — signe d'usure physique réelle")
        return {"success": True, "count": len(data), "disks": data, "warnings": warnings}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_event_log_errors(args: dict) -> dict:
    """Erreurs/critiques récentes des journaux d'événements Windows (Système + Application) —
    détecte des problèmes INTERMITTENTS (plantages, pilotes en échec, erreurs disque) invisibles
    dans un simple instantané CPU/RAM/disque. À inclure dans tout diagnostic PC complet."""
    try:
        days = max(1, min(int(args.get("days", 7)), 30))
        max_events = max(5, min(int(args.get("max_events", 20)), 50))
    except (TypeError, ValueError):
        return {"error": "Paramètres 'days' ou 'max_events' invalides."}
    try:
        result = await _run_powershell({
            "script": (
                f"Get-WinEvent -FilterHashtable @{{LogName='System','Application'; Level=1,2; "
                f"StartTime=(Get-Date).AddDays(-{days})}} -MaxEvents {max_events} -ErrorAction SilentlyContinue | "
                "Select-Object @{Name='TimeCreated';Expression={$_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss')}}, "
                "LevelDisplayName, ProviderName, Id, "
                "@{Name='Message';Expression={($_.Message -split \"`n\")[0]}} | "
                "ConvertTo-Json -Compress -Depth 2"
            ),
            "confirmed": True, "timeout": 25,
        })
        if result.get("error") or result.get("returncode") != 0:
            return {"error": result.get("error") or result.get("stderr") or "Échec PowerShell"}
        raw = result.get("stdout", "").strip()
        events = json.loads(raw) if raw else []
        if isinstance(events, dict):
            events = [events]
        from collections import Counter
        sources = Counter(e.get("ProviderName", "?") for e in events)
        recurring = [f"{name} ({count}×)" for name, count in sources.most_common(5) if count >= 2]
        return {
            "success": True, "period_days": days, "count": len(events),
            "events": events[:max_events], "recurring_sources": recurring,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_driver_check(args: dict) -> dict:
    """Vérifie si un pilote/composant a une version plus récente disponible, via une VRAIE
    recherche web ciblée (pas une supposition du modèle). Renvoie les résultats de recherche
    officiels/pertinents pour que tu puisses donner une réponse tranchée sur les pilotes,
    au lieu de dire « vérifie toi-même »."""
    component = str(args.get("component") or "").strip()
    installed_version = str(args.get("installed_version") or "").strip()
    if not component:
        return {"error": "Paramètre 'component' requis (ex: 'NVIDIA GeForce RTX 2060')."}
    query = f"{component} dernière version pilote driver download"
    result = await _web_search({"query": query, "max_results": 5})
    if not result.get("success"):
        return result
    return {
        "success": True,
        "component": component,
        "installed_version": installed_version or None,
        "query_used": query,
        "results": result.get("results", []),
        "note": ("Compare la version installée aux résultats ci-dessus — cite la source (URL) "
                 "dans ta réponse, ne devine jamais un numéro de version."),
    }


async def execute_pc_health_trend(args: dict) -> dict:
    """Tendance RÉELLE de santé du PC dans le temps (RAM, disque, usure SSD, erreurs
    récurrentes) — basée sur des instantanés quotidiens enregistrés automatiquement, pas une
    estimation. Utilise ceci pour répondre à « est-ce que ça empire ? », « dans combien de temps
    le disque sera plein ? » ou tout diagnostic qui bénéficie d'une vue dans la durée plutôt
    qu'un instantané isolé. Si moins de 2 points existent, le dis explicitement — pas de
    tendance calculable sur un seul instantané."""
    try:
        days = max(2, min(int(args.get("days", 30)), 90))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'days' invalide : entier attendu entre 2 et 90."}
    snapshots = db.get_system_snapshots(days=days)
    if len(snapshots) < 2:
        return {
            "success": True,
            "count": len(snapshots),
            "snapshots": snapshots,
            "trend_available": False,
            "message": ("Pas assez d'historique pour calculer une tendance "
                         f"({len(snapshots)} instantané(s) — il en faut au moins 2, "
                         "un par jour est enregistré automatiquement)."),
        }
    first, last = snapshots[0], snapshots[-1]
    try:
        from datetime import datetime as _dt
        d0 = _dt.fromisoformat(first["created_at"].replace(" ", "T"))
        d1 = _dt.fromisoformat(last["created_at"].replace(" ", "T"))
        span_days = max(1, (d1 - d0).days)
    except Exception:
        span_days = max(1, len(snapshots) - 1)

    def _delta_per_week(key):
        v0, v1 = first.get(key), last.get(key)
        if v0 is None or v1 is None:
            return None
        return round((v1 - v0) / span_days * 7, 1)

    ram_trend = _delta_per_week("ram_percent")
    disk_trend = _delta_per_week("disk_max_percent")
    warnings = []
    if disk_trend and disk_trend > 0 and last.get("disk_max_percent") is not None:
        remaining_pct = 100 - last["disk_max_percent"]
        weeks_to_full = round(remaining_pct / disk_trend, 1) if disk_trend > 0 else None
        if weeks_to_full and weeks_to_full < 12:
            warnings.append(
                f"⚠️ Au rythme actuel (+{disk_trend}%/semaine sur {last.get('disk_max_percent_drive')}), "
                f"le disque sera plein dans environ {weeks_to_full} semaine(s)."
            )
    if ram_trend and ram_trend > 5:
        warnings.append(f"⚠️ RAM en hausse de {ram_trend}%/semaine — à surveiller.")
    return {
        "success": True,
        "count": len(snapshots),
        "period_days": span_days,
        "snapshots": snapshots,
        "trend_available": True,
        "ram_percent_per_week": ram_trend,
        "disk_percent_per_week": disk_trend,
        "warnings": warnings,
    }


async def execute_pc_tool_reliability(args: dict) -> dict:
    """Introspection : taux d'échec RÉEL de chaque outil Marvin sur les N derniers jours (pas
    une estimation) — sépare le volume d'appels de la fiabilité. Chaque outil a aussi un taux
    RÉCENT (7 jours par défaut) et un flag likely_already_fixed : un mauvais taux sur la longue
    période mais 0 échec récemment est probablement déjà réglé, pas une priorité. Utilise ceci
    quand l'utilisateur demande quels outils échouent le plus, ou pour un audit de fiabilité
    auto-critique — privilégie les outils avec un mauvais taux RÉCENT, pas juste global."""
    try:
        min_calls = max(1, min(int(args.get("min_calls", 3)), 1000))
        days = max(1, min(int(args.get("days", 90)), 365))
        recent_days = max(1, min(int(args.get("recent_days", 7)), 90))
    except (TypeError, ValueError):
        return {
            "error": "Paramètres 'min_calls', 'days' ou 'recent_days' invalides."
        }
    rows = db.get_tool_reliability(min_calls=min_calls, days=days, recent_days=recent_days)
    still_concerning = [r for r in rows if not r["likely_already_fixed"]]
    return {
        "success": True,
        "period_days": days,
        "recent_days": recent_days,
        "count": len(rows),
        "tools": rows[:20],
        "note": (f"Trié par taux d'échec global décroissant. {len(rows) - len(still_concerning)} outil(s) "
                 f"ont un mauvais taux global mais 0 échec sur les {recent_days} derniers jours "
                 "(likely_already_fixed=true) — probablement déjà réglés, pas une priorité. "
                 "Concentre-toi sur ceux avec likely_already_fixed=false ET recent_failure_rate_pct élevé."),
    }


async def execute_pc_conversation_trace(args: dict) -> dict:
    """Chronologie complète des appels d'outils d'UNE conversation (durée de chacun, succès/
    échec, ordre réel) — remplace le recomptage manuel des appels fait pour diagnostiquer une
    lenteur. Utilise ceci quand l'utilisateur demande pourquoi une réponse a été lente ou veut
    un audit précis de ce qui s'est passé dans un échange."""
    conversation_id = str(args.get("conversation_id") or "").strip()
    if not conversation_id:
        return {"error": "Paramètre 'conversation_id' requis."}
    trace = db.get_conversation_trace(conversation_id)
    total_ms = sum(t.get("duration_ms") or 0 for t in trace)
    return {
        "success": True,
        "conversation_id": conversation_id,
        "count": len(trace),
        "total_duration_ms": total_ms,
        "trace": [
            {"tool": t.get("tool_name"), "success": t.get("success"),
             "duration_ms": t.get("duration_ms"), "created_at": t.get("created_at")}
            for t in trace
        ],
    }


async def execute_pc_installed_software(args: dict) -> dict:
    """Liste les LOGICIELS INSTALLÉS sur le PC (nom, version, éditeur) — sans argument à fournir.
    Lit la base de registre Windows (Uninstall) → fiable et complet. Pour « inventaire logiciel »,
    « liste des programmes installés », « quels logiciels sont sur ce PC »."""
    try:
        ps = (
            "$paths='HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
            "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*';"
            "Get-ItemProperty $paths -ErrorAction SilentlyContinue | "
            "Where-Object { $_.DisplayName } | "
            "Select-Object @{N='name';E={$_.DisplayName}},@{N='version';E={$_.DisplayVersion}},@{N='publisher';E={$_.Publisher}} | "
            "Sort-Object name -Unique | ConvertTo-Json -Compress"
        )
        result = await _run_powershell({"script": ps, "confirmed": True, "timeout": 30})
        if result.get("error"):
            return result
        import json as _j
        try:
            apps = _j.loads(result.get("stdout", "[]") or "[]")
            if isinstance(apps, dict):
                apps = [apps]
        except Exception:
            return {"error": "Impossible de lire la liste des logiciels installés."}
        apps = [a for a in apps if a.get("name")]
        return {
            "success": True,
            "count": len(apps),
            "software": apps[:600],
            "inventory_scope": "windows_uninstall_registry",
            "full_result_available_in_ui": True,
            "coverage_caveat": (
                "Cette source couvre les entrées Désinstaller du Registre, pas toutes les "
                "applications MSIX ni les exécutables portables."
            ),
            "message": f"{len(apps)} logiciel(s) enregistré(s) détecté(s) sur ce PC.",
        }
    except Exception as e:
        return {"error": str(e)}
