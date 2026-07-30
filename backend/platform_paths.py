"""Portable discovery of user and application paths without machine-bound literals."""
from __future__ import annotations

import os
import string
import tempfile
import uuid
from pathlib import Path
from typing import Final


_KNOWN_FOLDER_IDS: Final[dict[str, str]] = {
    "home": "5E6C858F-0E22-4760-9AFE-EA3317B67173",
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "appdata_roaming": "3EB685DB-65F9-4CF6-A03A-E3EF65729F3D",
    "appdata_local": "F1B32785-6FBA-4FCF-9D55-7B8E7F157091",
    "startup": "B97D20BB-F46A-4C97-BA10-5E3608430854",
}


def _known_folder(folder_id: str) -> str | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    raw = uuid.UUID(folder_id).bytes_le
    guid = GUID.from_buffer_copy(raw)
    output = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(output))
    if result != 0 or not output.value:
        return None
    try:
        return str(Path(output.value))
    finally:
        ole32.CoTaskMemFree(output)


def system_paths() -> dict[str, str]:
    """Resolve the current profile, including OneDrive and enterprise redirections."""
    fallback_home = Path(os.environ.get("USERPROFILE") or Path.home()).resolve()
    home = Path(_known_folder(_KNOWN_FOLDER_IDS["home"]) or fallback_home)
    fallbacks = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "pictures": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
        "appdata_roaming": Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming"),
        "appdata_local": Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local"),
        "startup": home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup",
    }
    resolved = {"home": str(home)}
    for name, fallback in fallbacks.items():
        resolved[name] = str(Path(_known_folder(_KNOWN_FOLDER_IDS[name]) or fallback))
    resolved["temp"] = str(Path(tempfile.gettempdir()).resolve())
    resolved["username"] = os.environ.get("USERNAME") or home.name
    resolved["drive"] = os.path.splitdrive(str(home))[0]
    return resolved


PATHS: Final[dict[str, str]] = system_paths()


def logical_drives() -> list[str]:
    """Liste les lecteurs Windows présents, avec un repli portable et borné."""
    if os.name != "nt":
        drive = os.path.splitdrive(PATHS["home"])[0]
        return [f"{drive}{os.sep}"] if drive else [os.path.abspath(os.sep)]
    import ctypes

    try:
        bitmask = int(ctypes.windll.kernel32.GetLogicalDrives())
        drives = [
            f"{letter}:\\"
            for index, letter in enumerate(string.ascii_uppercase)
            if bitmask & (1 << index)
        ]
        return drives or [f"{PATHS['drive']}\\"]
    except (AttributeError, OSError, TypeError, ValueError):
        return [f"{PATHS['drive']}\\"]


def expand_user_path(value: str) -> str:
    """Expand portable UI values and aliases against Windows Known Folders."""
    raw = os.path.expandvars(str(value or "").strip())
    if not raw:
        return PATHS["home"]
    aliases = {
        "home": "home", "accueil": "home", "bureau": "desktop", "desktop": "desktop",
        "documents": "documents", "downloads": "downloads", "telechargements": "downloads",
        "téléchargements": "downloads", "pictures": "pictures", "images": "pictures",
        "music": "music", "musique": "music", "videos": "videos", "vidéos": "videos",
    }
    portable = raw.replace("/", "\\").strip("\\")
    first, separator, remainder = portable.partition("\\")
    alias_key = aliases.get(first.casefold())
    if alias_key:
        return str(Path(PATHS[alias_key]) / remainder) if separator and remainder else PATHS[alias_key]
    if raw == "~":
        return PATHS["home"]
    if raw.startswith(("~/", "~\\")):
        return str(Path(PATHS["home"]) / raw[2:].replace("/", os.sep).replace("\\", os.sep))
    return raw
