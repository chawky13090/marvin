"""Domaine Windows : raccourcis, services et diagnostics natifs."""
from __future__ import annotations
import json
import os
import subprocess as _sp
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
import psutil
from platform_paths import PATHS as _SYSTEM_PATHS

PowerShellRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
async def _missing_powershell(args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "Runner PowerShell non configur?."}
_run_powershell: PowerShellRunner = _missing_powershell
def configure(*, run_powershell: PowerShellRunner) -> None:
    global _run_powershell
    _run_powershell = run_powershell


_WIN_SHORTCUTS = [
    {"id": "god_mode",         "group": "God Mode",         "label": "Dossier God Mode (tous les panneaux Windows)", "kind": "god_mode"},
    {"id": "settings_apps",             "group": "Paramètres Windows", "label": "Applications",                    "uri": "ms-settings:appsfeatures"},
    {"id": "settings_startup",          "group": "Paramètres Windows", "label": "Applications au démarrage",       "uri": "ms-settings:startupapps"},
    {"id": "settings_update",           "group": "Paramètres Windows", "label": "Windows Update",                  "uri": "ms-settings:windowsupdate"},
    {"id": "settings_defender",         "group": "Paramètres Windows", "label": "Sécurité Windows (Defender)",     "uri": "windowsdefender:"},
    {"id": "settings_privacy",          "group": "Paramètres Windows", "label": "Confidentialité",                 "uri": "ms-settings:privacy"},
    {"id": "settings_optional_features","group": "Paramètres Windows", "label": "Fonctionnalités facultatives",    "uri": "ms-settings:optionalfeatures"},
    {"id": "settings_power",            "group": "Paramètres Windows", "label": "Alimentation",                    "uri": "ms-settings:powersleep"},
    {"id": "settings_storage",          "group": "Paramètres Windows", "label": "Stockage",                        "uri": "ms-settings:storagesense"},
    {"id": "settings_activation",       "group": "Paramètres Windows", "label": "Activation",                      "uri": "ms-settings:activation"},
    {"id": "settings_developers",       "group": "Paramètres Windows", "label": "Espace développeurs",             "uri": "ms-settings:developers"},
    {"id": "control_programs", "group": "Panneaux legacy", "label": "Programmes et fonctionnalités", "cmd": ["control.exe", "appwiz.cpl"]},
    {"id": "control_network",  "group": "Panneaux legacy", "label": "Connexions réseau",             "cmd": ["control.exe", "ncpa.cpl"]},
    {"id": "control_system",   "group": "Panneaux legacy", "label": "Propriétés système",            "cmd": ["sysdm.cpl"]},
    {"id": "control_power",    "group": "Panneaux legacy", "label": "Options d'alimentation avancées", "cmd": ["control.exe", "powercfg.cpl"]},
    {"id": "control_firewall", "group": "Panneaux legacy", "label": "Pare-feu avancé",               "cmd": ["wf.msc"], "admin": True},
    {"id": "tools_services",       "group": "Outils admin", "label": "Services",                        "cmd": ["services.msc"], "admin": True},
    {"id": "tools_eventvwr",       "group": "Outils admin", "label": "Observateur d'événements",        "cmd": ["eventvwr.msc"]},
    {"id": "tools_taskschd",       "group": "Outils admin", "label": "Planificateur de tâches",         "cmd": ["taskschd.msc"]},
    {"id": "tools_diskmgmt",       "group": "Outils admin", "label": "Gestion des disques",             "cmd": ["diskmgmt.msc"], "admin": True},
    {"id": "tools_device_manager", "group": "Outils admin", "label": "Gestionnaire de périphériques",   "cmd": ["devmgmt.msc"], "admin": True},
    {"id": "tools_computer_mgmt",  "group": "Outils admin", "label": "Gestion de l'ordinateur",         "cmd": ["compmgmt.msc"], "admin": True},
    {"id": "tools_msconfig",       "group": "Outils admin", "label": "Configuration système (msconfig)", "cmd": ["msconfig.exe"], "admin": True},
    {"id": "tools_taskmgr", "group": "Performance", "label": "Gestionnaire des tâches",       "cmd": ["taskmgr.exe"]},
    {"id": "tools_resmon",  "group": "Performance", "label": "Moniteur de ressources",        "cmd": ["resmon.exe"]},
    {"id": "tools_perfmon", "group": "Performance", "label": "Analyseur de performances",     "cmd": ["perfmon.exe"]},
    {"id": "tools_cleanmgr", "group": "Maintenance", "label": "Nettoyage de disque Windows",  "cmd": ["cleanmgr.exe"]},
    {"id": "folder_temp",    "group": "Dossiers utiles", "label": "Dossier Temp utilisateur",     "path_env": "TEMP"},
    {"id": "folder_startup", "group": "Dossiers utiles", "label": "Dossier Démarrage utilisateur", "path": r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"},
]


def _win_is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _win_open_target(target: str) -> dict:
    """Ouvre un fichier/URI/raccourci Windows : os.startfile (rapide, natif), avec repli
    `cmd /c start` si indisponible (ex. certains contextes de session)."""
    import subprocess as _sp
    try:
        os.startfile(target)
        return {"ok": True, "target": target}
    except Exception as e:
        try:
            flags = _sp.CREATE_NO_WINDOW if hasattr(_sp, "CREATE_NO_WINDOW") else 0
            r = _sp.run(["cmd.exe", "/c", "start", "", target], capture_output=True, timeout=15, creationflags=flags)
            return {"ok": r.returncode == 0, "target": target}
        except Exception as e2:
            return {"ok": False, "target": target, "error": f"{e} / repli: {e2}"}


async def execute_win_quick_launch_list(args: dict) -> dict:
    """Liste les raccourcis Windows disponibles (catalogue « Windows+ »), groupés."""
    admin_now = _win_is_admin()
    items = [{**o, "requires_admin": bool(o.get("admin", False))} for o in _WIN_SHORTCUTS]
    groups = {}
    for it in items:
        groups.setdefault(it["group"], []).append({"id": it["id"], "label": it["label"], "requires_admin": it["requires_admin"]})
    return {"success": True, "count": len(items), "groups": groups, "currently_admin": admin_now}


async def execute_win_quick_launch(args: dict) -> dict:
    """Ouvre directement un panneau/outil Windows (God Mode, ms-settings, panneaux legacy,
    outils admin .msc, dossiers utiles) par son id. Utiliser win_quick_launch_list pour voir
    les id disponibles. N'écrit/ne modifie rien (sauf God Mode : crée un dossier vide standard)."""
    action_id = (args.get("id") or args.get("action_id") or "").strip()
    if not action_id:
        return {"error": "Paramètre 'id' requis. Utilise win_quick_launch_list pour voir les options."}
    item = next((x for x in _WIN_SHORTCUTS if x["id"] == action_id), None)
    if not item:
        return {"error": f"Raccourci inconnu : {action_id!r}. Utilise win_quick_launch_list."}

    if item.get("kind") == "god_mode":
        desktop = Path(_SYSTEM_PATHS["desktop"])
        god = desktop / "Marvin God Mode.{ED7BA470-8E54-465E-825C-99712043E01C}"
        god.mkdir(exist_ok=True)
        res = _win_open_target(str(god))
        return {"success": res["ok"], "path": str(god), "opened": res}

    if item.get("path_env") or item.get("path"):
        target = os.environ.get(item.get("path_env", ""), "") if item.get("path_env") else os.path.expandvars(item.get("path", ""))
        if not target:
            return {"error": "Chemin indisponible sur ce PC."}
        Path(target).mkdir(parents=True, exist_ok=True)
        res = _win_open_target(target)
        return {"success": res["ok"], "path": target, "opened": res}

    if item.get("uri"):
        res = _win_open_target(item["uri"])
        note = "Droits admin conseillés pour ce panneau." if item.get("admin") and not _win_is_admin() else None
        return {"success": res["ok"], "opened": res, "note": note}

    cmd = item.get("cmd") or []
    if not cmd:
        return {"error": "Raccourci mal configuré (aucune cible)."}
    target = cmd[0] if len(cmd) == 1 and cmd[0].lower().endswith((".msc", ".cpl", ".exe")) else None
    if target:
        res = _win_open_target(target)
    else:
        import subprocess as _sp
        flags = _sp.CREATE_NO_WINDOW if hasattr(_sp, "CREATE_NO_WINDOW") else 0
        try:
            r = _sp.run(cmd, capture_output=True, timeout=15, creationflags=flags)
            res = {"ok": r.returncode == 0, "target": " ".join(cmd)}
        except Exception as e:
            res = {"ok": False, "target": " ".join(cmd), "error": str(e)}
    return {"success": res["ok"], "opened": res}


async def execute_win_firewall_status(args: dict) -> dict:
    """État RÉEL du pare-feu Windows (profils Domaine/Privé/Public actifs ou non) + nombre de
    règles entrantes AUTORISÉES actives (surface d'attaque). Rendu structuré au lieu de parser
    du texte PowerShell brut — utilise ceci pour tout audit de sécurité poste."""
    try:
        result = await _run_powershell({
            "script": (
                "$profiles = Get-NetFirewallProfile | Select-Object Name, Enabled, "
                "DefaultInboundAction, DefaultOutboundAction; "
                "$inboundAllow = (Get-NetFirewallRule -Direction Inbound -Action Allow "
                "-Enabled True -ErrorAction SilentlyContinue | Measure-Object).Count; "
                "@{profiles=$profiles; inbound_allow_rules_count=$inboundAllow} | ConvertTo-Json -Depth 3 -Compress"
            ),
            "confirmed": True, "timeout": 20,
        })
        if result.get("error") or result.get("returncode") != 0:
            return {"error": result.get("error") or result.get("stderr") or "Échec PowerShell"}
        data = json.loads(result.get("stdout", "{}") or "{}")
        profiles = data.get("profiles", [])
        if isinstance(profiles, dict):
            profiles = [profiles]
        warnings = []
        for p in profiles:
            if not p.get("Enabled"):
                warnings.append(f"🔴 Profil {p.get('Name')} : pare-feu DÉSACTIVÉ")
        return {
            "success": True,
            "profiles": profiles,
            "inbound_allow_rules_count": data.get("inbound_allow_rules_count"),
            "warnings": warnings,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_win_services_list(args: dict) -> dict:
    """Liste les services Windows avec leur état (running/stopped/etc.)."""
    filter_name = args.get("filter", "").strip().lower()
    status_filter = args.get("status", "").strip().lower()  # running | stopped | etc.
    try:
        result = await _run_powershell({
            "script": (
                "Get-Service | Select-Object -Property Name,DisplayName,Status,StartType | "
                "ConvertTo-Json -Depth 2 -Compress"
            ),
            "confirmed": True,
            "timeout": 15,
        })
        if result.get("error"):
            return result
        import json as _j
        try:
            services = _j.loads(result.get("stdout", "[]"))
            if isinstance(services, dict):
                services = [services]
        except Exception:
            return {"error": "Impossible de parser la sortie PowerShell."}

        # Normalize
        out = []
        for s in services:
            name    = s.get("Name", "")
            display = s.get("DisplayName", "")
            status  = str(s.get("Status", "")).lower()
            stype   = s.get("StartType", "")
            # Map status int to name (Status can be enum number)
            status_map = {1: "stopped", 2: "start_pending", 3: "stop_pending",
                          4: "running", 5: "continue_pending", 6: "pause_pending", 7: "paused"}
            if status.isdigit():
                status = status_map.get(int(status), status)

            if filter_name and filter_name not in name.lower() and filter_name not in display.lower():
                continue
            if status_filter and status_filter != status:
                continue

            out.append({
                "name": name,
                "display_name": display,
                "status": status,
                "start_type": stype,
            })
        # Sort: running first, then alphabetical
        out.sort(key=lambda x: (0 if x["status"] == "running" else 1, x["name"].lower()))
        return {
            "success": True,
            "count": len(out),
            "running": sum(1 for s in out if s["status"] == "running"),
            "stopped": sum(1 for s in out if s["status"] == "stopped"),
            "services": out[:200],
        }
    except Exception as e:
        return {"error": str(e)}


async def _resolve_service_name(name: str) -> tuple[str | None, list[dict]]:
    """Résout un nom de service FLOU (nom d'affichage, casse différente, ordre des mots
    différent selon la langue — ex. "Windows Defender Firewall" vs "Pare-feu Windows
    Defender" sur un Windows en français) vers le nom INTERNE exact attendu par
    Get-Service/Start-Service/etc. (ex. "MpsSvc"). Renvoie (nom_résolu, []) si trouvé
    sans ambiguïté, ou (None, candidats) si plusieurs services correspondent."""
    safe = str(name).replace("'", "").replace("\r", " ").replace("\n", " ").strip()
    if not safe:
        return None, []
    exact = await _run_powershell({
        "script": f"Get-Service -Name '{safe}' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name",
        "confirmed": True, "timeout": 15,
    })
    out = (exact.get("stdout") or "").strip()
    if out and out not in ("(aucune sortie)", ""):
        return out.splitlines()[0].strip(), []
    fuzzy = await _run_powershell({
        "script": (f"Get-Service | Where-Object {{ $_.Name -like '*{safe}*' -or $_.DisplayName -like '*{safe}*' }} | "
                   "Select-Object Name, DisplayName | ConvertTo-Json -Compress"),
        "confirmed": True, "timeout": 15,
    })
    import json as _j
    try:
        candidates = _j.loads(fuzzy.get("stdout") or "[]")
        if isinstance(candidates, dict):
            candidates = [candidates]
    except Exception:
        candidates = []
    if len(candidates) == 1:
        return candidates[0]["Name"], []
    return None, candidates


async def execute_win_service_action(args: dict) -> dict:
    """Démarre, arrête, redémarre ou met en pause un service Windows."""
    name = str(args.get("name") or "").strip()
    action = str(args.get("action") or "").strip().lower()
    confirmed = args.get("confirmed", False)
    if not name:
        return {"error": "Paramètre 'name' requis."}

    # v2.113 — bug réel constaté : le LLM (et l'utilisateur) utilisent naturellement le nom
    # D'AFFICHAGE d'un service ("Windows Defender Firewall"), jamais son nom INTERNE exact
    # ("MpsSvc") qu'exigent Get-Service/Start-Service. Pire, sur un Windows localisé en
    # français, le nom d'affichage réel ("Pare-feu Windows Defender") a un ordre de mots
    # différent de l'anglais → même une recherche par sous-chaîne sur DisplayName échouait.
    # On résout maintenant nous-mêmes le nom exact avant toute lecture/action.
    resolved, candidates = await _resolve_service_name(name)
    if resolved:
        name = resolved
    elif candidates:
        options = ", ".join(f"{c.get('DisplayName')} ({c.get('Name')})" for c in candidates[:8])
        return {"error": f"Plusieurs services correspondent à « {name} » — précise avec le nom exact : {options}"}
    else:
        return {"success": False, "service": name,
                "message": f"Service « {name} » introuvable (vérifie le nom via win_services_list)."}

    # Lecture seule : interroger l'état d'un service (pas de confirmation requise).
    # Tolère les formulations naturelles du modèle (query/status/get/state/info).
    if action in ("query", "status", "get", "state", "info", "check"):
        result = await _run_powershell({
            "script": (f"Get-Service -Name '{name}' -ErrorAction SilentlyContinue | "
                       "Select-Object Name, DisplayName, Status, StartType | ConvertTo-Json"),
            "confirmed": True, "timeout": 20,
        })
        out = (result.get("stdout") or "").strip()
        if not out or out == "(aucune sortie)":
            return {"success": False, "service": name,
                    "message": f"Service « {name} » introuvable (vérifie le nom exact via win_services_list)."}
        return {"success": result.get("returncode") == 0, "action": "query",
                "service": name, "output": out}
    if action not in ("start", "stop", "restart", "pause", "resume"):
        return {"error": "Action invalide. Utilisez : query | start | stop | restart | pause | resume"}
    if not confirmed:
        return {
            "requiresConfirmation": True,
            "message": f"Confirmer l'action '{action}' sur le service '{name}' ? (peut nécessiter droits admin)",
        }
    try:
        ps_action = {
            "start":   f"Start-Service -Name '{name}' -PassThru",
            "stop":    f"Stop-Service -Name '{name}' -Force -PassThru",
            "restart": f"Restart-Service -Name '{name}' -Force -PassThru",
            "pause":   f"Suspend-Service -Name '{name}' -PassThru",
            "resume":  f"Resume-Service -Name '{name}' -PassThru",
        }[action]
        result = await _run_powershell({
            "script": f"{ps_action} | Select-Object Name, Status | ConvertTo-Json",
            "confirmed": True,
            "timeout": 30,
        })
        return {
            "success": result.get("returncode") == 0,
            "action": action,
            "service": name,
            "output": result.get("stdout", ""),
            "error": result.get("stderr", "") or None,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_win_event_log(args: dict) -> dict:
    """Lit les derniers événements du journal Windows (System / Application / Security)."""
    allowed_logs = {
        "system": "System",
        "application": "Application",
        "security": "Security",
        "setup": "Setup",
    }
    requested_log = str(args.get("log") or "System").strip().lower()
    log_name = allowed_logs.get(requested_log)
    if not log_name:
        return {"error": "Journal invalide : System, Application, Security ou Setup attendu."}
    try:
        max_events = max(1, min(int(args.get("max_events", 30)), 200))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'max_events' invalide : entier attendu entre 1 et 200."}
    level = str(args.get("level") or "").strip().lower()
    if level not in {"", "error", "warning", "information"}:
        return {"error": "Niveau invalide : error, warning ou information attendu."}

    level_filter = ""
    if level == "error":
        level_filter = " -EntryType Error"
    elif level == "warning":
        level_filter = " -EntryType Warning"
    elif level == "information":
        level_filter = " -EntryType Information"

    try:
        ps_script = (
            f"Get-EventLog -LogName '{log_name}' -Newest {max_events}{level_filter} | "
            "Select-Object TimeGenerated, EntryType, Source, EventID, "
            "@{Name='Message';Expression={$_.Message.Substring(0, [Math]::Min(200, $_.Message.Length))}} | "
            "ConvertTo-Json -Depth 2 -Compress"
        )
        result = await _run_powershell({
            "script": ps_script, "confirmed": True, "timeout": 20,
        })
        if result.get("error") or result.get("returncode") != 0:
            _err = result.get("error") or result.get("stderr") or result.get("stdout") or "Échec PowerShell"
            _el = str(_err).lower()
            if log_name.lower() == "security" or "access" in _el or "denied" in _el or "refus" in _el:
                return {"error": f"Lecture du journal « {log_name} » impossible — ce journal exige "
                                 f"souvent les droits ADMINISTRATEUR. Lance Marvin en administrateur, "
                                 f"ou utilise les journaux System/Application. Détail : {str(_err)[:140]}"}
            return {"error": str(_err)[:200]}
        import json as _j
        try:
            events = _j.loads(result.get("stdout", "[]"))
            if isinstance(events, dict):
                events = [events]
        except Exception:
            return {"error": "Impossible de parser la sortie."}
        return {
            "success": True,
            "log": log_name,
            "count": len(events),
            "events": events,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_win_users_list(args: dict) -> dict:
    """Liste les comptes utilisateurs locaux Windows."""
    try:
        result = await _run_powershell({
            "script": (
                "Get-LocalUser | Select-Object Name, Enabled, LastLogon, "
                "Description, PasswordExpires | ConvertTo-Json -Depth 2 -Compress"
            ),
            "confirmed": True, "timeout": 15,
        })
        if result.get("error") or result.get("returncode") != 0:
            return {"error": result.get("error") or result.get("stderr") or "Échec PowerShell"}
        import json as _j
        try:
            users = _j.loads(result.get("stdout", "[]"))
            if isinstance(users, dict):
                users = [users]
        except Exception:
            return {"error": "Impossible de parser la sortie."}
        return {"success": True, "count": len(users), "users": users}
    except Exception as e:
        return {"error": str(e)}


async def execute_win_disk_info(args: dict) -> dict:
    """Infos détaillées sur les disques Windows (partitions, espace, santé)."""
    try:
        result = await _run_powershell({
            "script": (
                "Get-Volume | Where-Object {$_.DriveLetter} | Select-Object DriveLetter, "
                "FileSystemLabel, FileSystem, "
                "@{Name='SizeGB';Expression={[math]::Round($_.Size/1GB,1)}}, "
                "@{Name='FreeGB';Expression={[math]::Round($_.SizeRemaining/1GB,1)}}, "
                "@{Name='UsedGB';Expression={[math]::Round(($_.Size - $_.SizeRemaining)/1GB,1)}}, "
                "@{Name='UsedPct';Expression={if($_.Size -gt 0){[math]::Round((($_.Size - $_.SizeRemaining)/$_.Size)*100,1)}else{0}}}, "
                "HealthStatus | ConvertTo-Json -Depth 2 -Compress"
            ),
            "confirmed": True, "timeout": 15,
        })
        if result.get("error") or result.get("returncode") != 0:
            return {"error": result.get("error") or result.get("stderr") or "Échec PowerShell"}
        import json as _j
        try:
            disks = _j.loads(result.get("stdout", "[]"))
            if isinstance(disks, dict):
                disks = [disks]
        except Exception:
            return {"error": "Impossible de parser la sortie."}
        return {"success": True, "count": len(disks), "disks": disks}
    except Exception as e:
        return {"error": str(e)}


async def execute_win_update_status(args: dict) -> dict:
    """Vérifie l'état des mises à jour Windows (dernière, en attente)."""
    try:
        result = await _run_powershell({
            "script": (
                "Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 10 "
                "HotFixID, Description, InstalledOn | ConvertTo-Json -Depth 2 -Compress"
            ),
            "confirmed": True, "timeout": 15,
        })
        if result.get("error") or result.get("returncode") != 0:
            return {"error": result.get("error") or result.get("stderr")}
        import json as _j
        try:
            hotfixes = _j.loads(result.get("stdout", "[]"))
            if isinstance(hotfixes, dict):
                hotfixes = [hotfixes]
        except Exception:
            return {"error": "Impossible de parser."}
        return {
            "success": True,
            "recent_updates": hotfixes,
            "count": len(hotfixes),
        }
    except Exception as e:
        return {"error": str(e)}


_win_diag_cache: dict = {}


async def _cached_ps_json(cache_key: str, script: str, ttl: float = 0, timeout: int = 20):
    """Exécute un script PowerShell renvoyant du JSON, avec cache optionnel."""
    import time as _t, json as _j
    now = _t.monotonic()
    if ttl > 0 and cache_key in _win_diag_cache:
        ts, data = _win_diag_cache[cache_key]
        if now - ts < ttl:
            return data, True  # (data, from_cache)
    result = await _run_powershell({"script": script, "confirmed": True, "timeout": timeout})
    if result.get("error") or result.get("returncode") != 0:
        return {"_error": result.get("error") or result.get("stderr") or "Échec PowerShell"}, False
    try:
        data = _j.loads(result.get("stdout", "[]") or "[]")
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return {"_error": "Impossible de parser la sortie PowerShell."}, False
    if ttl > 0:
        _win_diag_cache[cache_key] = (now, data)
    return data, False


async def execute_win_uptime(args: dict) -> dict:
    """Retourne l'uptime du système et la date de dernier démarrage."""
    data, cached = await _cached_ps_json(
        "uptime",
        "$os = Get-CimInstance Win32_OperatingSystem; "
        "$bt = $os.LastBootUpTime; $up = (Get-Date) - $bt; "
        "@{LastBoot=$bt.ToString('yyyy-MM-dd HH:mm:ss'); "
        "Days=$up.Days; Hours=$up.Hours; Minutes=$up.Minutes; "
        "TotalHours=[math]::Round($up.TotalHours,1)} | ConvertTo-Json -Compress",
        ttl=10,
    )
    if isinstance(data, dict) and data.get("_error"):
        return {"error": data["_error"]}
    info = data[0] if isinstance(data, list) and data else data
    return {
        "success": True,
        "last_boot": info.get("LastBoot"),
        "uptime_days": info.get("Days"),
        "uptime_hours": info.get("Hours"),
        "uptime_minutes": info.get("Minutes"),
        "total_hours": info.get("TotalHours"),
        "human": f"{info.get('Days',0)}j {info.get('Hours',0)}h {info.get('Minutes',0)}min",
    }


async def execute_win_startup_programs(args: dict) -> dict:
    """Liste les programmes lancés au démarrage de Windows (diagnostic boot lent)."""
    data, cached = await _cached_ps_json(
        "startup",
        "Get-CimInstance Win32_StartupCommand | "
        "Select-Object Name, Command, Location, User | ConvertTo-Json -Depth 2 -Compress",
        ttl=30,
    )
    if isinstance(data, dict) and data.get("_error"):
        return {"error": data["_error"]}
    return {
        "success": True,
        "count": len(data),
        "from_cache": cached,
        "startup_programs": data[:100],
    }


async def execute_win_scheduled_tasks(args: dict) -> dict:
    """Liste les tâches planifiées Windows (filtrable, exclut Microsoft par défaut)."""
    include_microsoft = args.get("include_microsoft", False)
    filter_state = args.get("state", "")  # Ready | Running | Disabled
    where = "" if include_microsoft else "| Where-Object {$_.TaskPath -notlike '\\Microsoft\\*'}"
    data, cached = await _cached_ps_json(
        f"sched_{include_microsoft}",
        f"Get-ScheduledTask {where} | "
        "Select-Object TaskName, TaskPath, State, "
        "@{N='Author';E={$_.Author}} | ConvertTo-Json -Depth 2 -Compress",
        ttl=30, timeout=25,
    )
    if isinstance(data, dict) and data.get("_error"):
        return {"error": data["_error"]}
    tasks = data
    if filter_state:
        tasks = [t for t in tasks if str(t.get("State", "")).lower() == filter_state.lower()]
    return {
        "success": True,
        "count": len(tasks),
        "from_cache": cached,
        "tasks": tasks[:150],
    }


async def execute_win_network_config(args: dict) -> dict:
    """Configuration réseau complète : adaptateurs, IPs, passerelle, DNS."""
    data, cached = await _cached_ps_json(
        "netconfig",
        "Get-NetIPConfiguration | ForEach-Object { "
        "@{Interface=$_.InterfaceAlias; "
        "Status=$_.NetAdapter.Status; "
        "IPv4=($_.IPv4Address.IPAddress -join ', '); "
        "Gateway=($_.IPv4DefaultGateway.NextHop -join ', '); "
        "DNS=($_.DNSServer.ServerAddresses -join ', '); "
        "MAC=$_.NetAdapter.MacAddress} } | ConvertTo-Json -Depth 3 -Compress",
        ttl=15,
    )
    if isinstance(data, dict) and data.get("_error"):
        return {"error": data["_error"]}
    return {
        "success": True,
        "count": len(data),
        "from_cache": cached,
        "adapters": data,
    }


async def execute_win_system_report(args: dict) -> dict:
    """
    Rapport diagnostic système complet en UN SEUL appel :
    OS, uptime, CPU, RAM, disques, réseau, top processus, mises à jour.
    Idéal pour un diagnostic rapide lors d'un support.
    """
    import json as _j
    try:
        # psutil pour les métriques rapides (pas de PowerShell)
        mem = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=0.3)
        disks = []
        for dp in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(dp.mountpoint)
                disks.append({
                    "drive": dp.device, "total_gb": round(u.total/1024**3, 1),
                    "free_gb": round(u.free/1024**3, 1), "used_pct": u.percent,
                })
            except Exception:
                pass
        # Top 5 processus par RAM
        procs = []
        for p in psutil.process_iter(['name', 'memory_info']):
            try:
                procs.append((p.info['name'], p.info['memory_info'].rss))
            except Exception:
                pass
        procs.sort(key=lambda x: x[1], reverse=True)
        top_procs = [{"name": n, "ram_mb": round(r/1024**2, 1)} for n, r in procs[:5]]

        # OS + uptime via une seule commande PowerShell
        report_extra = {}
        try:
            ps_data, _ = await _cached_ps_json(
                "sysreport",
                "$os = Get-CimInstance Win32_OperatingSystem; "
                "$cs = Get-CimInstance Win32_ComputerSystem; "
                "$up = (Get-Date) - $os.LastBootUpTime; "
                "@{OS=$os.Caption; Version=$os.Version; Build=$os.BuildNumber; "
                "Hostname=$cs.Name; Domain=$cs.Domain; "
                "Manufacturer=$cs.Manufacturer; Model=$cs.Model; "
                "UptimeDays=$up.Days; UptimeHours=$up.Hours} | ConvertTo-Json -Compress",
                ttl=20,
            )
            if isinstance(ps_data, list) and ps_data:
                report_extra = ps_data[0]
            elif isinstance(ps_data, dict) and not ps_data.get("_error"):
                report_extra = ps_data
        except Exception:
            pass

        # Synthèse + alertes
        alerts = []
        if mem.percent > 85:
            alerts.append(f"⚠️ RAM élevée : {mem.percent}%")
        if cpu_pct > 85:
            alerts.append(f"⚠️ CPU élevé : {cpu_pct}%")
        for d in disks:
            if d["used_pct"] > 90:
                alerts.append(f"⚠️ Disque {d['drive']} presque plein : {d['used_pct']}%")

        return {
            "success": True,
            "os": report_extra.get("OS", "Windows"),
            "os_version": report_extra.get("Version", ""),
            "build": report_extra.get("Build", ""),
            "hostname": report_extra.get("Hostname", ""),
            "domain": report_extra.get("Domain", ""),
            "manufacturer": report_extra.get("Manufacturer", ""),
            "model": report_extra.get("Model", ""),
            "uptime": f"{report_extra.get('UptimeDays',0)}j {report_extra.get('UptimeHours',0)}h",
            "cpu_percent": cpu_pct,
            "cpu_cores": psutil.cpu_count(),
            "ram_total_gb": round(mem.total/1024**3, 1),
            "ram_used_gb": round(mem.used/1024**3, 1),
            "ram_percent": mem.percent,
            "disks": disks,
            "top_processes": top_procs,
            "alerts": alerts,
            "health": "⚠️ Attention requise" if alerts else "✅ Système sain",
        }
    except Exception as e:
        return {"error": str(e)}
