"""Domaine de contr?le PC : bureau, commandes, GUI, presse-papiers et processus."""
from __future__ import annotations
import asyncio
import base64
import base64 as _b64
import datetime as _dt
import io
import os
import platform
import re as _re
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any
import psutil
from config import OLLAMA_URL
from platform_paths import PATHS as _SYSTEM_PATHS, logical_drives

_HOME = _SYSTEM_PATHS["home"]
_REAL_USER = _SYSTEM_PATHS["username"]
_DRIVE = _SYSTEM_PATHS["drive"]
PathResolver = Callable[[str], str]
SizeFormatter = Callable[[int], str]
_resolve_path: PathResolver
_format_size: SizeFormatter

_GUI_INTERACTIVE_TYPES = {
    "Button", "Edit", "Document", "ComboBox", "CheckBox", "RadioButton", "MenuItem", "MenuBar",
    "ListItem", "List", "TabItem", "Hyperlink", "Slider", "Spinner", "TreeItem",
    "SplitButton", "ToggleButton", "DataItem",
}
_GUI_CONTENT_TYPES = {"Edit", "Document"}


def configure(*, resolve_path: PathResolver, format_size: SizeFormatter) -> None:
    global _resolve_path, _format_size
    _resolve_path = resolve_path
    _format_size = format_size


async def execute_pc_get_real_paths(args: dict) -> dict:
    """Retourne tous les vrais chemins du PC courant — à appeler si incertain sur les chemins."""
    import platform, winreg
    home = _HOME
    username = _REAL_USER
    drive = _DRIVE

    paths = dict(_SYSTEM_PATHS)

    # Essayer de lire les chemins via le registre Windows (OneDrive, etc.)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
            for reg_name, our_name in [
                ("Desktop", "desktop"),
                ("Personal", "documents"),
                ("{374DE290-123F-4565-9164-39C4925E467B}", "downloads"),
                ("My Pictures", "pictures"),
                ("My Music", "music"),
                ("My Video", "videos"),
            ]:
                try:
                    val, _ = winreg.QueryValueEx(key, reg_name)
                    if val:
                        paths[our_name] = val
                except Exception:
                    pass
    except Exception:
        pass

    # Lister les dossiers existants sur le bureau, documents et téléchargements
    desktop_items, docs_items, downloads_items = [], [], []
    try:
        desktop_items = [f.name for f in Path(paths["desktop"]).iterdir()
                         if not f.name.startswith(".")][:20]
    except Exception:
        pass
    try:
        docs_items = [f.name for f in Path(paths["documents"]).iterdir()
                      if not f.name.startswith(".")][:20]
    except Exception:
        pass
    try:
        downloads_items = [f.name for f in Path(paths["downloads"]).iterdir()
                           if not f.name.startswith(".")][:20]
    except Exception:
        pass

    return {
        "success": True,
        "paths": paths,
        "desktop_contents": desktop_items,
        "documents_contents": docs_items,
        "downloads_contents": downloads_items,
        "instruction": (
            f"CHEMINS RÉELS : bureau={paths['desktop']}, "
            f"documents={paths['documents']}, "
            f"téléchargements={paths['downloads']}, "
            f"utilisateur={username}. "
            f"N'UTILISE JAMAIS d'autres noms d'utilisateur que '{username}'."
        ),
    }


def _quick_access():
    """Accès rapides (dossiers utilisateur + lecteurs) pour l'explorateur."""
    home = _HOME
    qa = []
    for label, path_key, icon in [
        ("Accueil", "home", "🏠"), ("Bureau", "desktop", "🖥️"), ("Documents", "documents", "📄"),
        ("Téléchargements", "downloads", "⬇️"), ("Images", "pictures", "🖼️"),
        ("Musique", "music", "🎵"), ("Vidéos", "videos", "🎬"),
    ]:
        p = _SYSTEM_PATHS[path_key]
        if os.path.isdir(p):
            qa.append({"label": label, "path": p, "icon": icon, "type": "folder"})
    for d in logical_drives():
        qa.append({"label": d.rstrip("\\"), "path": d, "icon": "💽", "type": "drive"})
    return qa


async def execute_pc_browse(args: dict) -> dict:
    """
    🗂️ Explore un dossier Windows : sous-dossiers + fichiers avec métadonnées
    (taille, date, type), + accès rapides (dossiers utilisateur, lecteurs).
    Permet de NAVIGUER l'arborescence sans taper les chemins.
    """
    from datetime import datetime as _dt
    raw = (args.get("path") or "").strip()
    show_hidden = bool(args.get("show_hidden", False))

    path = _HOME if (not raw or raw.lower() in ("home", "roots", "quick", "~")) else _resolve_path(raw)

    # Si on pointe sur un fichier → on explore son dossier parent (et on le signale)
    selected_file = None
    if os.path.isfile(path):
        selected_file = path
        path = os.path.dirname(path)

    if not os.path.isdir(path):
        return {"error": f"Dossier introuvable : {path}", "roots": _quick_access()}

    entries = []
    try:
        with os.scandir(path) as it:
            for e in it:
                name = e.name
                try:
                    is_dir = e.is_dir()
                    # Filtre des éléments cachés/système sauf si demandé
                    if not show_hidden:
                        if name.startswith("."):
                            continue
                        try:
                            attrs = os.stat(e.path).st_file_attributes
                            if attrs & 0x2 or attrs & 0x4:   # HIDDEN ou SYSTEM
                                continue
                        except Exception:
                            pass
                    st = e.stat()
                    entries.append({
                        "name": name,
                        "path": e.path,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else st.st_size,
                        "size_human": "" if is_dir else _format_size(st.st_size),
                        "modified": _dt.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "ext": "" if is_dir else os.path.splitext(name)[1].lower().lstrip("."),
                    })
                except (PermissionError, OSError):
                    continue
    except PermissionError:
        return {"error": f"Accès refusé : {path}", "roots": _quick_access()}
    except Exception as e:
        return {"error": str(e), "roots": _quick_access()}

    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    parent = os.path.dirname(path.rstrip("\\/"))
    if not parent or parent == path:
        parent = None

    return {
        "success": True,
        "path": path,
        "parent": parent,
        "roots": _quick_access(),
        "count": len(entries),
        "folders": sum(1 for e in entries if e["is_dir"]),
        "files": sum(1 for e in entries if not e["is_dir"]),
        "selected_file": selected_file,
        "entries": entries[:2000],
    }


async def execute_pc_open_file(args: dict) -> dict:
    raw = args.get("path", "")
    path = _resolve_path(raw)
    if not os.path.exists(path):
        # Repli : ce n'est peut-être pas un fichier mais un nom d'application
        # (ex. "firefox", "teraterm") — le modèle confond parfois file_open/app_launch.
        # Heuristique : pas de séparateur de chemin ni d'extension → probablement une appli.
        looks_like_app = "\\" not in raw and "/" not in raw and "." not in os.path.basename(raw or "")
        if looks_like_app and raw.strip():
            result = await execute_pc_app_launch({"app_name": raw.strip()})
            if result.get("success"):
                return result
        return {"error": f"Introuvable : {path}"}
    try:
        os.startfile(path)
        return {"success": True, "message": f"Ouvert : {path}"}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_reveal(args: dict) -> dict:
    """Ouvre l'Explorateur Windows sur l'emplacement d'un fichier/dossier (sélectionné)."""
    path = _resolve_path(args.get("path", ""))
    if not os.path.exists(path):
        return {"error": f"Introuvable : {path}"}
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.path.isdir(path):
            os.startfile(path)
        else:
            # /select met le fichier en surbrillance dans son dossier
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)], creationflags=flags)
        return {"success": True, "message": f"Révélé dans l'Explorateur : {path}"}
    except Exception as e:
        return {"error": str(e)}


def _find_app_target(name: str):
    """
    Résout le chemin d'une application Windows par son nom, dans l'ordre :
      1. PATH (shutil.which)
      2. App Paths du registre (chrome, spotify, code… s'y enregistrent)
      3. Raccourcis du menu Démarrer (.lnk) — couvre quasiment tout ce qui est installé
      4. Emplacements Program Files courants
    Retourne (kind, path) avec kind ∈ {'exe','lnk',None}.
    """
    import shutil
    n = (name or "").strip()
    if not n:
        return (None, None)
    low = n.lower()
    base = low[:-4] if low.endswith(".exe") else low

    # 1. PATH
    for cand in (n, n + ".exe"):
        w = shutil.which(cand)
        if w:
            return ("exe", w)

    # 1b. Alias d'exécution des apps du Store (Spotify, WhatsApp…)
    wa = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\WindowsApps")
    if os.path.isdir(wa):
        for cand in (base + ".exe", n + ".exe"):
            p = os.path.join(wa, cand)
            if os.path.exists(p):
                return ("exe", p)

    # 2. App Paths (HKCU puis HKLM, vues 64 et 32 bits)
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for flag in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                for sub in (n, n + ".exe", base + ".exe"):
                    try:
                        k = winreg.OpenKey(hive,
                                rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{sub}",
                                0, winreg.KEY_READ | flag)
                        val, _ = winreg.QueryValueEx(k, None)
                        winreg.CloseKey(k)
                        if val and os.path.exists(val.strip('"')):
                            return ("exe", val.strip('"'))
                    except OSError:
                        pass
    except Exception:
        pass

    # 3. Raccourcis du menu Démarrer (.lnk) — recherche floue par nom
    start_dirs = [
        os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
    ]
    best, best_score = None, 0.0
    for d in start_dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in files:
                if not f.lower().endswith((".lnk", ".url")):
                    continue
                stem = f.rsplit(".", 1)[0].lower()
                if stem == base:
                    return ("lnk", os.path.join(root, f))           # correspondance exacte
                if base in stem or stem in base:
                    score = len(base) / max(len(stem), 1)
                    if score > best_score:
                        best_score, best = score, os.path.join(root, f)
    if best:
        return ("lnk", best)

    # 4. Emplacements d'installation courants
    for pf in (os.environ.get("ProgramFiles", r"C:\Program Files"),
               os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
               os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if not pf or not os.path.isdir(pf):
            continue
        try:
            for entry in os.listdir(pf):
                if base.replace(" ", "") in entry.lower().replace(" ", ""):
                    exe = os.path.join(pf, entry, base + ".exe")
                    if os.path.exists(exe):
                        return ("exe", exe)
                    app_dir = os.path.join(pf, entry)
                    if not os.path.isdir(app_dir):
                        continue
                    executables = [
                        item for item in os.listdir(app_dir)
                        if item.lower().endswith(".exe")
                        and not item.lower().startswith(
                            ("unins", "uninstall", "update", "crash")
                        )
                    ]
                    if len(executables) == 1:
                        return ("exe", os.path.join(app_dir, executables[0]))
                    preferred_suffix = "64.exe" if os.environ.get(
                        "PROCESSOR_ARCHITECTURE", ""
                    ).endswith("64") else "32.exe"
                    preferred = [
                        item for item in executables
                        if item.lower().endswith(preferred_suffix)
                    ]
                    if len(preferred) == 1:
                        return ("exe", os.path.join(app_dir, preferred[0]))
        except Exception:
            pass
    return (None, None)


def _application_evidence(expected_names: set[str], title_hint: str) -> dict:
    processes = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = str(process.info.get("name") or "").lower()
            if name in expected_names:
                processes.append({"pid": int(process.info["pid"]), "name": name})
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            continue

    windows = []
    normalized_hint = title_hint.casefold().strip()
    if normalized_hint:
        try:
            import win32gui

            def collect(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd).strip()
                if normalized_hint in title.casefold():
                    windows.append(title[:200])

            win32gui.EnumWindows(collect, None)
        except Exception:
            pass
    return {
        "processes": processes,
        "window_visible": bool(windows),
        "window_titles": windows,
    }


def _expected_process_names(kind: str, target: str) -> set[str]:
    if kind in {"exe", "path"}:
        return {Path(target).name.lower()}
    if kind != "lnk":
        return set()
    try:
        import win32com.client

        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(target)
        resolved = str(shortcut.Targetpath or "").strip()
        return {Path(resolved).name.lower()} if resolved else set()
    except Exception:
        return set()


async def _launch_and_verify(
    *,
    app_name: str,
    kind: str,
    target: str,
    expected_names: set[str] | None = None,
) -> dict:
    expected_names = expected_names or _expected_process_names(kind, target)
    title_hint = app_name if len(app_name.strip()) >= 3 else ""
    before = _application_evidence(expected_names, title_hint)
    try:
        os.startfile(target)
    except OSError as exc:
        return {
            "success": False,
            "dispatched": False,
            "verified": False,
            "needs_repair": True,
            "error": f"Impossible de lancer « {app_name} » : {exc}",
            "method": kind,
            "resolved": target,
        }

    after = before
    for _attempt in range(20):
        await asyncio.sleep(0.25)
        after = _application_evidence(expected_names, title_hint)
        if after["processes"] or after["window_visible"]:
            break
    verified = bool(after["processes"] or after["window_visible"])
    return {
        "success": verified,
        "dispatched": True,
        "verified": verified,
        "needs_repair": not verified,
        "message": (
            f"Application ouverte et vérifiée : {app_name}"
            if verified
            else f"Lancement demandé, mais aucune preuve d'ouverture pour « {app_name} »."
        ),
        "method": kind,
        "resolved": target,
        "expected_processes": sorted(expected_names),
        "before": before,
        "after": after,
    }


async def execute_pc_app_launch(args: dict) -> dict:
    app_name = args.get("app_name", "")
    aliases = {
        # Navigateurs
        "chrome": "chrome", "google chrome": "chrome",
        "firefox": "firefox",
        "edge": "msedge", "microsoft edge": "msedge",
        "brave": "brave",
        "opera": "opera",
        # Microsoft Office
        "word": "winword", "microsoft word": "winword",
        "excel": "excel", "microsoft excel": "excel",
        "powerpoint": "powerpnt", "microsoft powerpoint": "powerpnt",
        "access": "msaccess", "publisher": "mspub",
        "outlook": "outlook", "microsoft outlook": "outlook",
        "onenote": "onenote",
        "teams": "teams", "microsoft teams": "teams",
        # Windows intégrés
        "notepad": "notepad", "bloc-notes": "notepad",
        "notepad++": "notepad++",
        "explorer": "explorer", "file explorer": "explorer",
        "gestionnaire de fichiers": "explorer",
        "calculator": "calc", "calculatrice": "calc",
        "paint": "mspaint",
        "wordpad": "wordpad",
        "task manager": "taskmgr", "gestionnaire des tâches": "taskmgr",
        "settings": "ms-settings:", "paramètres": "ms-settings:",
        "control panel": "control", "panneau de configuration": "control",
        "registry": "regedit", "registre": "regedit",
        "event viewer": "eventvwr", "journal d'événements": "eventvwr",
        "device manager": "devmgmt.msc", "gestionnaire de périphériques": "devmgmt.msc",
        "disk management": "diskmgmt.msc", "gestion des disques": "diskmgmt.msc",
        "services": "services.msc",
        # Terminaux
        "terminal": "wt", "windows terminal": "wt",
        "cmd": "cmd", "invite de commandes": "cmd",
        "powershell": "powershell",
        # Développement
        "vscode": "code", "visual studio code": "code", "vs code": "code",
        "git": "git-gui",
        # Médias & Autres
        "vlc": "vlc",
        "spotify": "spotify",
        "discord": "discord",
        "slack": "slack",
        "zoom": "zoom",
        "skype": "skype",
        "steam": "steam",
        "winrar": "winrar",
        "7zip": "7zFM", "7-zip": "7zFM",
        "obs": "obs64", "obs studio": "obs64",
    }
    if not app_name.strip():
        return {"error": "Paramètre 'app_name' requis."}
    key = app_name.lower().strip()
    if key in {"tailscale", "tailscale gui", "interface tailscale"}:
        from tool_domains import tailscale as tailscale_domain
        return await tailscale_domain.open_ui()
    cmd = aliases.get(key, app_name).strip()

    try:
        # Protocoles / URL Windows (ms-settings:, shell:, http://…)
        if cmd.startswith(("ms-", "shell:")) or "://" in cmd:
            expected = set()
            if cmd.startswith("ms-settings:"):
                expected = {"systemsettings.exe"}
            elif cmd.startswith("shell:"):
                expected = {"explorer.exe"}
            return await _launch_and_verify(
                app_name=app_name,
                kind="protocol",
                target=cmd,
                expected_names=expected,
            )

        # Snap-ins MMC (.msc)
        if cmd.lower().endswith(".msc"):
            return await _launch_and_verify(
                app_name=app_name,
                kind="mmc",
                target=cmd,
                expected_names={"mmc.exe"},
            )

        # Chemin absolu fourni directement
        if os.path.isabs(cmd) and os.path.exists(cmd):
            return await _launch_and_verify(
                app_name=app_name, kind="path", target=cmd
            )

        # ── Résolution robuste : PATH → App Paths → menu Démarrer → Program Files ──
        kind, target = _find_app_target(cmd)
        if kind:
            return await _launch_and_verify(
                app_name=app_name, kind=kind, target=target
            )

        # Dernier recours : laisser Windows tenter (alias UWP, commandes intégrées)
        try:
            os.startfile(cmd)
            return {
                "success": False,
                "dispatched": True,
                "verified": False,
                "needs_repair": True,
                "message": (
                    f"Windows a reçu la demande pour « {app_name} », mais Marvin "
                    "n'a pas pu identifier l'application afin de vérifier son ouverture."
                ),
                "method": "startfile_unverified",
            }
        except Exception:
            pass

        return {"error": f"Application « {app_name} » introuvable. "
                         f"Vérifiez le nom exact ou qu'elle est bien installée. "
                         f"Astuce : essayez le nom du raccourci tel qu'il apparaît dans le menu Démarrer."}
    except Exception as e:
        return {"error": f"Impossible de lancer « {app_name} » : {e}"}


_PWSH_ALREADY_INVOKED_RE = _re.compile(
    r'^\s*"?(?:[a-zA-Z]:\\[^"]*\\)?(?:powershell|pwsh)(?:\.exe)?"?(?:\s|$)', _re.I
)


def _looks_like_powershell(command: str) -> bool:
    """Détecte une commande qui est en réalité du PowerShell (cmdlets Verb-Noun,
    opérateurs/pipelines PS, variables $_). Évite l'erreur classique « Get-ChildItem
    n'est pas reconnu » quand on l'exécute par erreur dans cmd.exe."""
    c = (command or "")
    cl = c.lower()
    # Cmdlet Verb-Noun (Get-NetFirewallProfile, Get-MpComputerStatus, Get-LocalUser…)
    if _re.search(r"\b(get|set|new|remove|add|start|stop|restart|test|select|where|"
                  r"foreach|out|write|read|import|export|convertto|convertfrom|measure|"
                  r"sort|group|format|enable|disable|invoke|clear|copy|move|rename|update|"
                  r"install|uninstall|find|search|resolve|show|join|split|compare|tee)-[a-z][a-z0-9]+",
                  cl):
        return True
    # Opérateurs / éléments propres à PowerShell
    ps_markers = ("select-object", "where-object", "foreach-object", "$_", "$psitem",
                  "| select", "| where", "| foreach", "| sort", "| measure", "| format-",
                  "[pscustomobject]", "-executionpolicy", "get-content", "write-host",
                  "-erroraction", "$env:", ".count", "out-string")
    return any(m in cl for m in ps_markers)


async def execute_pc_run_command(args: dict) -> dict:
    command = str(args.get("command") or "").strip()
    if not command:
        return {"error": "Paramètre 'command' requis."}
    import security as _sec                      # 🛡️ garde-fou : bloque le catastrophique
    _blk = _sec.guard_result(command)
    if _blk:
        return _blk
    if not args.get("confirmed"):
        msg = f"Exécuter la commande : {command} ?"
        _mismatch = _sec.detect_cross_platform_mismatch(command)
        if _mismatch:
            msg = _mismatch + "\n\n" + msg
        return {"requiresConfirmation": True, "message": msg}
    try:
        timeout = max(1, min(int(args.get("timeout", 30)), 600))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'timeout' invalide : entier attendu entre 1 et 600."}
    # Auto-routage : si la commande est en fait du PowerShell, on l'exécute via PowerShell
    # (sinon cmd.exe renvoie « commande introuvable »). Rend les compétences robustes.
    # v2.183 -- SAUF si la commande invoque DEJA explicitement powershell.exe/pwsh (ex.
    # `powershell -Command "..."` ou `powershell -File script.ps1`) : dans ce cas, la router
    # quand meme vers execute_pc_run_powershell la ferait executer comme -EncodedCommand,
    # c-a-d que TOUT le texte -- y compris le `powershell -Command "..."` d'origine -- devient
    # le CONTENU du script. PowerShell interpole alors les `$variable` a l'interieur de cette
    # chaine entre guillemets AVANT meme de lancer le powershell imbrique voulu, les vidant
    # silencieusement (`$bmp = New-Object ...` devient ` = New-Object ...`). Bug reel trouve en
    # rejouant une conversation ou 7 tentatives consecutives de generation de logo ont echoue
    # avec exactement ce symptome. Une commande qui invoque deja powershell.exe est deja bien
    # formee pour un lancement direct via cmd.exe (qui n'interprete jamais `$`) -- pas besoin
    # (et dangereux) de la re-emballer.
    if _looks_like_powershell(command) and not _PWSH_ALREADY_INVOKED_RE.match(command):
        ps_res = await execute_pc_run_powershell({"script": command, "timeout": timeout, "confirmed": True})
        if isinstance(ps_res, dict):
            ps_res["shell"] = "powershell (auto)"
        return ps_res
    try:
        # Use CREATE_NO_WINDOW to avoid antivirus triggering on visible console windows
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        # asyncio.to_thread : subprocess.run bloque, sinon toute l'event loop FastAPI se
        # fige (chat, /api/health…) pendant la durée de la commande (jusqu'à `timeout`).
        result = await asyncio.to_thread(
            subprocess.run,
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
            creationflags=flags,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip() or "Aucune sortie standard.",
            "stderr": result.stderr.strip() or "",
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Délai dépassé ({timeout}s)"}
    except PermissionError:
        return {"error": "Permission refusée — votre antivirus bloque cette commande."}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_run_powershell(args: dict) -> dict:
    """Exécute un script ou commande PowerShell et retourne la sortie."""
    script = str(args.get("script") or "").strip()
    if not script:
        return {"error": "Paramètre 'script' requis."}
    try:
        timeout = max(1, min(int(args.get("timeout", 30)), 600))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'timeout' invalide : entier attendu entre 1 et 600."}
    import security as _sec                      # 🛡️ garde-fou : bloque le catastrophique
    _blk = _sec.guard_result(script)
    if _blk:
        return _blk
    if not args.get("confirmed"):
        preview = script[:120] + ("…" if len(script) > 120 else "")
        msg = f"Exécuter ce script PowerShell ?\n{preview}"
        _mismatch = _sec.detect_cross_platform_mismatch(script)
        if _mismatch:
            msg = _mismatch + "\n\n" + msg
        return {"requiresConfirmation": True, "message": msg}
    import base64 as _b64
    # Use EncodedCommand to avoid antivirus string-matching on the script content.
    # UTF-16-LE is required by PowerShell's -EncodedCommand parameter.
    # Forcer la sortie en UTF-8 → les accents (é, è, à…) ne sont plus mojibake côté Python.
    script = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;$OutputEncoding=[System.Text.Encoding]::UTF8;" + script
    encoded = _b64.b64encode(script.encode("utf-16-le")).decode("ascii")

    # Prefer the full system32 path to avoid antivirus blocking "powershell" in PATH
    ps_candidates = [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        r"C:\Windows\SysWow64\WindowsPowerShell\v1.0\powershell.exe",
        "powershell.exe",
        "powershell",
    ]
    ps_exe = next((p for p in ps_candidates if os.path.exists(p) if "\\" in p), "powershell.exe")

    try:
        # v2.135 — trouvé en corrigeant le hang signalé sur le diagnostic PC complet (pas le
        # hang lui-même — les outils individuels répondaient tous en 1-2s, la lenteur perçue
        # était juste la somme normale de ~8 appels d'outils+LLM en chaîne — mais un VRAI bug
        # trouvé au passage) : capturé en `text=True, encoding="utf-8"` avec `errors="replace"`,
        # silencieux — malgré le `[Console]::OutputEncoding=UTF8` injecté en tête de script, la
        # sortie de PowerShell en mode `-EncodedCommand` + stdout redirigé reste en pratique
        # encodée en Windows-1252 (confirmé : l'apostrophe typographique "'" de Windows, octet
        # 0x92 en cp1252, décodée comme UTF-8 invalide → "�" — observé sur `win_event_log` ET
        # le nouveau `pc_event_log_errors`, donc préexistant, pas introduit par les outils
        # v2.134). Capture désormais les OCTETS bruts et essaie UTF-8 strict d'abord (certains
        # scripts/outils l'émettent réellement) — n'échoue silencieusement sur cp1252 QUE si le
        # décodage UTF-8 échoue vraiment, au lieu de toujours forcer UTF-8 avec des caractères
        # perdus.
        result = await asyncio.to_thread(
            subprocess.run,
            [ps_exe, "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            capture_output=True, text=False, timeout=timeout,
            # Avoid spawning a visible window (antivirus sometimes intercepts this)
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )

        def _decode(raw: bytes) -> str:
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("cp1252", errors="replace")

        stdout_text = _decode(result.stdout)
        stderr_text = _decode(result.stderr)
        # Filtrer le bruit CLIXML de PowerShell (progress/info streams en XML)
        stderr_clean = stderr_text.strip()
        if stderr_clean.startswith("#< CLIXML"):
            stderr_clean = ""
        stdout_clean = stdout_text.strip() or "(aucune sortie)"
        self_reported_failure = bool(
            _re.search(r"(?im)^\s*\[x\]\s+", stdout_clean)
            or _re.search(
                r"(?im)^\s*\[!\].*(?:échec|echec|encore présent|encore present|"
                r"dossier restant|introuvable|impossible de supprimer)",
                stdout_clean,
            )
            or _re.search(
                r"(?im)aucun package installé ne correspond aux critères",
                stdout_clean,
            )
        )
        business_success = result.returncode == 0 and not stderr_clean and not self_reported_failure
        return {
            "success":    business_success,
            "returncode": result.returncode,
            "stdout":     stdout_clean,
            "stderr":     stderr_clean,
            "process_completed": result.returncode == 0,
            "business_verification": (
                "failed"
                if self_reported_failure
                else ("passed" if business_success else "unknown")
            ),
            **(
                {
                    "error": (
                        "PowerShell s'est terminé, mais la sortie du script signale "
                        "qu'au moins un objectif métier n'est pas atteint."
                    )
                }
                if self_reported_failure
                else {}
            ),
        }
    except FileNotFoundError:
        return {"error": "PowerShell introuvable. Vérifiez qu'il est installé et accessible."}
    except subprocess.TimeoutExpired:
        return {"error": f"Délai dépassé ({timeout}s)"}
    except PermissionError:
        return {"error": "Permission refusée — votre antivirus bloque l'exécution. Ajoutez le dossier backend à la liste blanche."}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_run_elevated(args: dict) -> dict:
    """Exécute une commande AVEC DROITS ADMINISTRATEUR, via le démon élevé séparé
    (le backend principal reste en utilisateur normal). Nécessite confirmation."""
    command = str(args.get("command") or "").strip()
    script = str(args.get("script") or "").strip()
    if not command and not script:
        return {"error": "Paramètre 'command' (cmd) ou 'script' (PowerShell) requis."}
    payload = script or command
    action = "run_powershell" if script else "run_command"

    import security as _sec   # 🛡️ garde-fou côté demandeur AUSSI (défense en profondeur ;
    _blk = _sec.guard_result(payload)   # le démon la revérifie de toute façon côté élevé.
    if _blk:
        return _blk

    if not args.get("confirmed"):
        preview = payload[:140] + ("…" if len(payload) > 140 else "")
        return {"requiresConfirmation": True,
                "message": f"⚠️ Exécuter EN ADMINISTRATEUR : {preview} ?"}

    import elevated_client as _ec
    if not _ec.is_daemon_available():
        return {"error": "🔒 Démon élevé non lancé. Lance `backend/launch_elevated_daemon.ps1` "
                         "(une invite Windows apparaît une fois), puis réessaie.",
                "daemon_unavailable": True}
    timeout = max(5, min(int(args.get("timeout", 30)), 300))
    kwarg = {"command": payload} if action == "run_command" else {"script": payload}
    return await _ec.call_elevated(action, timeout=timeout, **kwarg)


async def execute_pc_system_info(args: dict) -> dict:
    try:
        mem = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=0.5)
        disks = []
        for dp in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(dp.mountpoint)
                disks.append({
                    "device": dp.device,
                    "mountpoint": dp.mountpoint,
                    "total_gb": round(usage.total / 1024**3, 1),
                    "used_gb": round(usage.used / 1024**3, 1),
                    "free_gb": round(usage.free / 1024**3, 1),
                    "percent": usage.percent,
                })
            except Exception:
                pass

        import platform
        uname = platform.uname()
        boot_time = psutil.boot_time()
        uptime_s = int(time.time() - boot_time)
        uptime_str = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m"

        def fmt(n): return f"{n / 1024**3:.1f} Go"

        # Batterie (laptops uniquement)
        battery_info = None
        try:
            bat = psutil.sensors_battery()
            if bat is not None:
                battery_info = {
                    "percent": round(bat.percent, 1),
                    "plugged": bat.power_plugged,
                    "status": "En charge" if bat.power_plugged else "Sur batterie",
                }
                if bat.secsleft and bat.secsleft != psutil.POWER_TIME_UNLIMITED and bat.secsleft > 0:
                    h = bat.secsleft // 3600
                    m = (bat.secsleft % 3600) // 60
                    battery_info["time_left"] = f"{h}h {m}m"
        except Exception:
            pass

        # Réseau — interfaces actives
        net_ifaces = []
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for iface, addr_list in addrs.items():
                st = stats.get(iface)
                if st and st.isup:
                    ipv4 = next((a.address for a in addr_list if a.family.name == "AF_INET"), "")
                    if ipv4 and not ipv4.startswith("127."):
                        net_ifaces.append({"name": iface, "ip": ipv4, "speed_mbps": st.speed})
        except Exception:
            pass

        info = {
            "success": True,
            "platform": uname.system,
            "release": uname.release,
            "arch": uname.machine,
            "uptime": uptime_str,
            "cpu_percent": cpu_pct,
            "cpu_count_logical": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "memory": {
                "total": fmt(mem.total),
                "used": fmt(mem.used),
                "free": fmt(mem.available),
                "percent": mem.percent,
            },
            "disks": disks,
            "network_interfaces": net_ifaces,
            "home": _HOME,
        }
        if battery_info:
            info["battery"] = battery_info
        return info
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_screenshot(args: dict) -> dict:
    # Accepte "path" (UI outils) ou "output_path" (agent)
    output_path = args.get("output_path") or args.get("path") or None
    embed = args.get("embed", False)  # True → retourner base64 au lieu de sauvegarder
    if output_path:
        output_path = _resolve_path(output_path)
    else:
        desktop = Path(_SYSTEM_PATHS["desktop"])
        output_path = str(desktop / f"screenshot_{int(time.time())}.png")
    try:
        from PIL import ImageGrab
        import io, base64
        screenshot = ImageGrab.grab()
        if embed:
            buf = io.BytesIO()
            screenshot.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return {
                "success": True,
                "message": "Capture d'écran prise",
                "image": f"data:image/png;base64,{b64}",
            }
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        screenshot.save(output_path)
        return {"success": True, "message": f"Capture d'écran sauvegardée : {output_path}", "path": output_path}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_window_list(args: dict) -> dict:
    try:
        import win32gui
        windows = []

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and title.strip():
                    windows.append({"hwnd": hwnd, "title": title})

        win32gui.EnumWindows(cb, None)
        return {"success": True, "count": len(windows), "windows": windows}
    except ImportError:
        # Fallback: use tasklist
        result = await asyncio.to_thread(
            subprocess.run,
            "tasklist /FO CSV /NH", shell=True, capture_output=True, text=True, timeout=10
        )
        lines = [l.strip().strip('"') for l in result.stdout.splitlines() if l.strip()]
        windows = [{"title": l.split('","')[0]} for l in lines[:50]]
        return {"success": True, "count": len(windows), "windows": windows}
    except Exception as e:
        return {"error": str(e)}


# v2.539 — Incident réel reproduit (conversation « Ouvrir IT Connect sur Firefox »,
# après redémarrage) : `SetForegroundWindow` a échoué avec `(258, 'SetForegroundWindow',
# 'Dépassement du délai d'attente.')` — Windows refuse de céder le focus à un process
# qui n'a pas l'entrée utilisateur la plus récente (anti-vol de focus). Contournement
# standard win32 : attacher temporairement l'input du thread de la fenêtre au premier
# plan à celui de la fenêtre cible le temps de l'appel, ce qui autorise le transfert.
def _set_foreground_resilient(hwnd: int) -> None:
    import win32gui
    import win32process
    import win32api
    import win32con

    try:
        win32gui.SetForegroundWindow(hwnd)
        return
    except Exception:
        pass
    current = win32gui.GetForegroundWindow()
    current_thread = win32process.GetWindowThreadProcessId(current)[0] if current else 0
    target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
    this_thread = win32api.GetCurrentThreadId()
    attached_current = attached_target = False
    try:
        if current_thread and current_thread != this_thread:
            win32process.AttachThreadInput(this_thread, current_thread, True)
            attached_current = True
        if target_thread and target_thread != this_thread:
            win32process.AttachThreadInput(this_thread, target_thread, True)
            attached_target = True
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    finally:
        if attached_current:
            win32process.AttachThreadInput(this_thread, current_thread, False)
        if attached_target:
            win32process.AttachThreadInput(this_thread, target_thread, False)


async def execute_pc_window_focus(args: dict) -> dict:
    search = str(args.get("search", "") or "").strip()
    requested_hwnd = args.get("hwnd")
    if not search and requested_hwnd is None:
        return {"error": "Paramètre 'search' ou 'hwnd' requis."}
    try:
        import win32gui
        import win32con

        # v2.537 — Incident réel reproduit (conversation « Liste des éléments du
        # bureau ») : le modèle cible régulièrement une fenêtre par le `hwnd`
        # renvoyé par observe/list_windows (identifiant exact, sans ambiguïté de
        # titre) — non supporté jusqu'ici, le paramètre était rejeté par le
        # schéma. Priorité au hwnd exact quand fourni, sans changer le
        # comportement existant par titre.
        if requested_hwnd is not None:
            try:
                hwnd = int(requested_hwnd)
            except (TypeError, ValueError):
                return {"error": "Paramètre 'hwnd' invalide : entier attendu."}
            if not win32gui.IsWindow(hwnd):
                return {"error": f"Aucune fenêtre avec le hwnd {hwnd}"}
            title = win32gui.GetWindowText(hwnd)
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            _set_foreground_resilient(hwnd)
            return {"success": True, "message": f"Fenêtre mise au premier plan : {title}"}

        candidates: list[tuple[int, str]] = []

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and title.strip():
                    candidates.append((hwnd, title))

        win32gui.EnumWindows(cb, None)
        target = _select_window_for_focus(search, candidates)
        if target:
            hwnd, title = target
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            _set_foreground_resilient(hwnd)
            return {"success": True, "message": f"Fenêtre mise au premier plan : {title}"}
        return {"error": f"Aucune fenêtre contenant « {search} » trouvée"}
    except Exception as e:
        return {"error": str(e)}


def _normalised_title_tokens(value: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    return {
        token
        for token in _re.findall(r"[a-z0-9]+", ascii_text)
        if len(token) >= 2
    }


def _select_window_for_focus(
    search: str,
    candidates: list[tuple[int, str]],
) -> tuple[int, str] | None:
    """Tolère la ponctuation d'un titre sans sélectionner une fenêtre ambiguë."""
    if not search:
        return None
    exact_title = [
        candidate
        for candidate in candidates
        if search.casefold() == candidate[1].casefold()
    ]
    if len(exact_title) == 1:
        return exact_title[0]
    substring_matches = [
        candidate
        for candidate in candidates
        if search.casefold() in candidate[1].casefold()
    ]
    if len(substring_matches) == 1:
        return substring_matches[0]
    if len(substring_matches) > 1:
        return None

    requested = _normalised_title_tokens(search)
    if len(requested) < 2:
        return None
    ranked: list[tuple[float, int, tuple[int, str]]] = []
    for candidate in candidates:
        title_tokens = _normalised_title_tokens(candidate[1])
        shared = len(requested & title_tokens)
        score = shared / len(requested)
        if shared >= 2 and score >= 0.6:
            ranked.append((score, shared, candidate))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if not ranked:
        return None
    if (
        len(ranked) > 1
        and ranked[0][0] == ranked[1][0]
        and ranked[0][1] == ranked[1][1]
    ):
        return None
    return ranked[0][2]


def _gui_get_window_sync(search: str):
    """Connecte à une fenêtre top-level via UI Automation. search vide → fenêtre au premier plan."""
    from pywinauto import Desktop
    import win32gui

    desktop = Desktop(backend="uia")
    if not search:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError("Aucune fenêtre au premier plan.")
        title = win32gui.GetWindowText(hwnd)
        return desktop.window(handle=hwnd), title
    search_l = search.lower()
    for w in desktop.windows():
        try:
            title = w.window_text()
        except Exception:
            continue
        if title and search_l in title.lower():
            return w, title
    raise RuntimeError(f"Aucune fenêtre contenant « {search} » trouvée (ou fenêtre élevée/admin, inaccessible).")


def _gui_read_sync(search: str, max_elements: int) -> dict:
    window, title = _gui_get_window_sync(search)
    elements = []
    counter: dict = {}
    try:
        descendants = window.descendants()
    except Exception as e:
        raise RuntimeError(f"Lecture de l'arbre UI impossible (fenêtre élevée/admin ?) : {e}")
    for ctrl in descendants:
        try:
            ctype = ctrl.element_info.control_type or ""
            if ctype not in _GUI_INTERACTIVE_TYPES:
                continue
            name_raw = (ctrl.window_text() or "").strip()
            auto_id = ctrl.element_info.automation_id or ""
            # v2.150 — Windows masque déjà le contenu des champs mot de passe au niveau UI
            # Automation lui-même (vérifié en réel : IsPassword=True → window_text()/get_value()
            # renvoient tous deux "" pour un WinForms PasswordChar) — rien à faire pour empêcher
            # une fuite ici. On étiquette juste explicitement le champ pour que ni le LLM ni
            # l'utilisateur ne confondent un name vide "masqué par l'OS" avec un champ inconnu.
            is_password = False
            try:
                is_password = bool(ctrl.element_info.element.CurrentIsPassword)
            except Exception:
                pass
            if ctype in _GUI_CONTENT_TYPES and not name_raw and not is_password:
                try:
                    name_raw = str(ctrl.get_value() or "").strip()
                except Exception:
                    try:
                        name_raw = str(
                            ctrl.iface_text.DocumentRange.GetText(-1) or ""
                        ).strip()
                    except Exception:
                        pass
            if (
                not name_raw
                and not auto_id
                and not is_password
                and ctype not in _GUI_CONTENT_TYPES
            ):
                continue
            enabled = ctrl.is_enabled()
            visible = ctrl.is_visible()
        except Exception:
            continue
        # Pour Edit/Document, le contenu n'est jamais une clé de matching (cf. note ci-dessus).
        match_key_name = "" if ctype in _GUI_CONTENT_TYPES else name_raw
        display_name = "(champ mot de passe — masqué par Windows)" if is_password else \
            ((name_raw[:100] + "…") if len(name_raw) > 100 else name_raw)
        key = (ctype, match_key_name)
        idx = counter.get(key, 0)
        counter[key] = idx + 1
        elements.append({
            "control_type": ctype, "name": display_name, "automation_id": auto_id,
            "match_index": idx, "enabled": enabled, "visible": visible, "is_password": is_password,
        })
        if len(elements) >= max_elements:
            break
    return {"success": True, "window_title": title, "count": len(elements), "elements": elements}


def _gui_resolve_sync(search: str, control_type: str, name: str, automation_id: str, match_index: int):
    window, title = _gui_get_window_sync(search)
    if automation_id:
        # pywinauto 0.6.9 ne transmet pas ``auto_id`` à descendants() avec le
        # backend UIA. Filtrer les métadonnées évite l'exception IUIA.build_condition
        # observée en conditions réelles avec Yandex Browser.
        matches = [
            control
            for control in window.descendants(control_type=control_type)
            if str(control.element_info.automation_id or "") == automation_id
        ] if control_type else [
            control
            for control in window.descendants()
            if str(control.element_info.automation_id or "") == automation_id
        ]
    elif control_type in _GUI_CONTENT_TYPES:
        # Contenu non fiable comme clé (cf. _GUI_CONTENT_TYPES) — matching par position uniquement.
        matches = window.descendants(control_type=control_type)
    else:
        matches = [c for c in window.descendants(control_type=control_type)
                   if (c.window_text() or "").strip() == name]
    if not matches:
        raise RuntimeError(
            "Élément introuvable — l'interface a changé depuis la dernière lecture "
            "(refais un pc_gui_read pour re-vérifier l'état actuel)."
        )
    idx = min(max(match_index, 0), len(matches) - 1)
    return window, title, matches[idx]


async def execute_pc_gui_read(args: dict) -> dict:
    search = str(args.get("window") or "").strip()
    try:
        max_elements = max(1, min(int(args.get("max_elements", 40)), 100))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'max_elements' invalide : entier attendu entre 1 et 100."}
    try:
        return await asyncio.to_thread(_gui_read_sync, search, max_elements)
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_gui_click(args: dict) -> dict:
    search = str(args.get("window") or "").strip()
    control_type = str(args.get("control_type") or "").strip()
    name = str(args.get("name") or "").strip()
    automation_id = str(args.get("automation_id") or "").strip()
    try:
        match_index = max(0, int(args.get("match_index", 0)))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'match_index' invalide : entier positif attendu."}
    if not control_type and not automation_id:
        return {"error": "Paramètre 'control_type' ou 'automation_id' requis (issus d'un pc_gui_read récent)."}
    if not args.get("confirmed"):
        target_desc = automation_id or f"{control_type} « {name} »"
        return {"requiresConfirmation": True,
                "message": f"Cliquer sur l'élément {target_desc} dans la fenêtre "
                            f"« {search or '(premier plan)'} » ?"}

    def _click():
        window, title, ctrl = _gui_resolve_sync(search, control_type, name, automation_id, match_index)
        if not ctrl.is_enabled():
            raise RuntimeError("Élément désactivé — impossible de cliquer.")
        ctrl.click_input()
        return title

    try:
        title = await asyncio.to_thread(_click)
        return {"success": True, "message": f"Clic effectué sur « {name or automation_id} » dans « {title} »."}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_gui_type(args: dict) -> dict:
    search = str(args.get("window") or "").strip()
    control_type = str(args.get("control_type") or "").strip()
    name = str(args.get("name") or "").strip()
    automation_id = str(args.get("automation_id") or "").strip()
    try:
        match_index = max(0, int(args.get("match_index", 0)))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'match_index' invalide : entier positif attendu."}
    text = str(args.get("text") or "")
    if not control_type and not automation_id:
        return {"error": "Paramètre 'control_type' ou 'automation_id' requis (issus d'un pc_gui_read récent)."}
    if not text:
        return {"error": "Paramètre 'text' requis."}
    if not args.get("confirmed"):
        target_desc = automation_id or f"{control_type} « {name} »"
        preview = text[:80] + ("…" if len(text) > 80 else "")
        return {"requiresConfirmation": True,
                "message": f"Écrire « {preview} » dans l'élément {target_desc} de la fenêtre "
                            f"« {search or '(premier plan)'} » ?"}

    def _type():
        window, title, ctrl = _gui_resolve_sync(search, control_type, name, automation_id, match_index)
        if not ctrl.is_enabled():
            raise RuntimeError("Élément désactivé — impossible d'y écrire.")
        ctrl.set_focus()
        if control_type == "Document":
            ctrl.click_input()
            ctrl.type_keys("^a{BACKSPACE}")
            ctrl.type_keys(text, with_spaces=True)
        else:
            try:
                ctrl.set_edit_text(text)
            except Exception:
                ctrl.type_keys(text, with_spaces=True)
        return title

    try:
        title = await asyncio.to_thread(_type)
        return {"success": True, "message": f"Texte écrit dans « {name or automation_id} » de « {title} »."}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_notify(args: dict) -> dict:
    title = args.get("title", "SecretaryAI")
    message = args.get("message", "")
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="Marvin",
            timeout=10,
        )
        return {"success": True, "message": "Notification envoyée"}
    except Exception:
        # Fallback via PowerShell toast (use -EncodedCommand to avoid injection)
        try:
            import base64
            # Escape backtick then double-quote for PS double-quoted strings
            safe_title   = title.replace("`", "``").replace('"', '`"')
            safe_message = message.replace("`", "``").replace('"', '`"')
            ps = (
                f'[Windows.UI.Notifications.ToastNotificationManager,'
                f'Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null;'
                f'$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent('
                f'[Windows.UI.Notifications.ToastTemplateType]::ToastText02);'
                f'$xml.GetElementsByTagName("text")[0].AppendChild($xml.CreateTextNode("{safe_title}")) | Out-Null;'
                f'$xml.GetElementsByTagName("text")[1].AppendChild($xml.CreateTextNode("{safe_message}")) | Out-Null;'
                f'$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);'
                f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("SecretaryAI").Show($toast);'
            )
            encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
            await asyncio.to_thread(subprocess.run, ["powershell", "-NoProfile", "-EncodedCommand", encoded], timeout=5, capture_output=True)
            return {"success": True, "message": "Notification envoyée"}
        except Exception as e2:
            return {"error": str(e2)}


async def execute_pc_pull_ollama_model(args: dict) -> dict:
    model = args.get("model", "llama3.2:3b")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/pull",
                json={"name": model},
                timeout=600.0,
            )
            resp.raise_for_status()
        return {"success": True, "message": f"Modèle téléchargé : {model}"}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_clipboard_get(args: dict) -> dict:
    # 1. win32clipboard (rapide, fiable) — vérifie le format AVANT de lire pour
    #    éviter l'exception sur presse-papiers vide / non-texte, et ferme toujours.
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
            elif win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_TEXT):
                raw = win32clipboard.GetClipboardData(win32clipboard.CF_TEXT) or b""
                text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            else:
                # Détecte les contenus non-texte (image, fichiers) pour informer l'utilisateur
                has_img = win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB)
                has_files = win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP)
                kind = "image" if has_img else "fichier(s)" if has_files else "vide"
                return {"success": True, "text": "", "empty": True, "content_type": kind,
                        "message": f"Le presse-papiers ne contient pas de texte ({kind})."}
        finally:
            win32clipboard.CloseClipboard()
        return {"success": True, "text": text, "length": len(text), "empty": text == ""}
    except Exception:
        pass
    # 2. Fallback PowerShell (décodage binaire sûr pour éviter le crash cp1252)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = (result.stdout or b"").decode("utf-8", "replace").rstrip("\r\n")
        return {"success": True, "text": text, "length": len(text), "empty": text == ""}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_clipboard_set(args: dict) -> dict:
    text = args.get("text", "")
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()
        return {"success": True, "message": "Texte copié dans le presse-papiers"}
    except Exception:
        try:
            import base64
            # Use -EncodedCommand to avoid shell injection with special characters/quotes
            ps_script = f"Set-Clipboard -Value '{text.replace(chr(39), chr(39)+chr(39))}'"
            encoded = base64.b64encode(ps_script.encode('utf-16-le')).decode('ascii')
            await asyncio.to_thread(
                subprocess.run,
                f'powershell -NoProfile -EncodedCommand {encoded}', shell=True, timeout=5
            )
            return {"success": True, "message": "Texte copié dans le presse-papiers"}
        except Exception as e:
            return {"error": str(e)}


async def execute_pc_process_list(args: dict) -> dict:
    sort_by = args.get("sort_by", "memory")  # cpu | memory | name
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
            try:
                info = p.info
                procs.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "cpu_percent": info["cpu_percent"] or 0.0,
                    "memory_mb": round(info["memory_info"].rss / 1024**2, 1) if info["memory_info"] else 0,
                    "status": info["status"],
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if sort_by == "cpu":
            procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
        elif sort_by == "name":
            procs.sort(key=lambda x: x["name"].lower())
        else:  # memory (défaut)
            procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        return {"success": True, "count": len(procs), "processes": procs[:50]}
    except Exception as e:
        return {"error": str(e)}


async def execute_pc_process_kill(args: dict) -> dict:
    pid = args.get("pid")
    name = str(args.get("name") or "").strip()
    if pid in (None, "") and not name:
        return {"error": "PID ou nom de processus requis"}
    if pid not in (None, ""):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return {"error": "PID invalide : entier positif attendu."}
        if pid <= 0:
            return {"error": "PID invalide : entier positif attendu."}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"Arrêter le processus {name or ''} (PID {pid}) ?"}
    try:
        if pid:
            proc = psutil.Process(int(pid))
            proc.terminate()
            return {"success": True, "message": f"Processus {pid} terminé"}
        elif name:
            killed = 0
            for p in psutil.process_iter(["pid", "name"]):
                if name.lower() in p.info["name"].lower():
                    p.terminate()
                    killed += 1
            return {"success": True, "message": f"{killed} processus '{name}' terminés"}
        return {"error": "PID ou nom de processus requis"}
    except Exception as e:
        return {"error": str(e)}
