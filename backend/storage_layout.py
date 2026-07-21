"""Portable, classified storage roots for Marvin runtime assets and user exports."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Final

from config import DATA_DIR
from platform_paths import PATHS


CONFIG_PATH: Final[Path] = Path(DATA_DIR) / "storage_layout.json"
MACHINE_SUBDIRECTORIES: Final[tuple[str, ...]] = (
    "library/iso/windows",
    "library/iso/linux",
    "library/vm/windows",
    "library/vm/linux",
    "workspaces/code",
    "workspaces/missions",
    "artifacts/tests",
    "artifacts/builds",
    "cache",
    "logs",
    "temp",
)
EXPORT_SUBDIRECTORIES: Final[tuple[str, ...]] = (
    "documents",
    "reports",
    "code",
    "media/images",
    "media/audio",
    "media/video",
)


class StorageLayoutError(RuntimeError):
    pass


def _load_config() -> dict[str, str]:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {str(key): str(item) for key, item in value.items()} if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_config(value: dict[str, str]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, CONFIG_PATH)


def _default_roots() -> tuple[Path, Path]:
    machine = Path(
        os.environ.get("MARVIN_MACHINE_ROOT")
        or Path(PATHS["appdata_local"]) / "Marvin"
    )
    exports = Path(
        os.environ.get("MARVIN_EXPORT_ROOT")
        or Path(PATHS["documents"]) / "Marvin"
    )
    return machine, exports


def roots() -> tuple[Path, Path]:
    configured = _load_config()
    default_machine, default_exports = _default_roots()
    machine = Path(configured.get("machine_root") or default_machine).expanduser().resolve()
    exports = Path(configured.get("export_root") or default_exports).expanduser().resolve()
    return machine, exports


def _drive_type(path: Path) -> str:
    if os.name != "nt":
        return "local"
    import ctypes

    anchor = path.anchor or os.path.splitdrive(str(path))[0] + "\\"
    value = ctypes.windll.kernel32.GetDriveTypeW(str(anchor))
    return {
        0: "unknown", 1: "invalid", 2: "removable", 3: "fixed",
        4: "network", 5: "optical", 6: "ramdisk",
    }.get(int(value), "unknown")


def _cloud_roots() -> list[Path]:
    names = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial", "Dropbox", "GoogleDrive")
    values = []
    for name in names:
        raw = os.environ.get(name)
        if raw:
            try:
                values.append(Path(raw).expanduser().resolve())
            except OSError:
                continue
    return values


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_machine_root(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    drive_type = _drive_type(resolved)
    cloud_root = next((str(item) for item in _cloud_roots() if _is_within(resolved, item)), None)
    issues = []
    if drive_type not in {"fixed", "local"}:
        issues.append(f"La bibliothèque machine exige un disque local fixe, type observé : {drive_type}.")
    if cloud_root:
        issues.append("Les ISO et VHDX ne doivent pas être stockés dans un dossier synchronisé cloud.")
    try:
        usage = shutil.disk_usage(resolved.anchor or resolved)
        free_bytes = usage.free
    except OSError:
        free_bytes = 0
        issues.append("Espace disque impossible à mesurer.")
    return {
        "path": str(resolved), "drive_type": drive_type, "cloud_root": cloud_root,
        "free_bytes": free_bytes, "valid": not issues, "issues": issues,
    }


def configure(*, machine_root: str, export_root: str, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise StorageLayoutError("La modification des racines doit être confirmée.")
    machine = Path(os.path.expandvars(machine_root)).expanduser().resolve()
    exports = Path(os.path.expandvars(export_root)).expanduser().resolve()
    machine_validation = validate_machine_root(machine)
    if not machine_validation["valid"]:
        raise StorageLayoutError(" ".join(machine_validation["issues"]))
    if machine == exports or _is_within(machine, exports) or _is_within(exports, machine):
        raise StorageLayoutError("Les racines machine et exports doivent rester séparées.")
    _write_config({"machine_root": str(machine), "export_root": str(exports)})
    return ensure(confirmed=True)


def _inventory_iso(root: Path) -> list[dict[str, Any]]:
    result = []
    for category in ("windows", "linux"):
        directory = root / "library" / "iso" / category
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.iso"), key=lambda item: item.name.casefold()):
            try:
                stat = path.stat()
            except OSError:
                continue
            result.append({
                "name": path.name, "path": str(path), "category": category,
                "size_bytes": stat.st_size, "modified_at": stat.st_mtime,
            })
    return result


def status() -> dict[str, Any]:
    machine, exports = roots()
    validation = validate_machine_root(machine)
    return {
        "machine_root": str(machine), "export_root": str(exports),
        "configured": CONFIG_PATH.exists(), "machine": validation,
        "machine_exists": machine.is_dir(), "export_exists": exports.is_dir(),
        "directories": {
            "iso_windows": str(machine / "library" / "iso" / "windows"),
            "iso_linux": str(machine / "library" / "iso" / "linux"),
            "vm_windows": str(machine / "library" / "vm" / "windows"),
            "vm_linux": str(machine / "library" / "vm" / "linux"),
            "code_workspaces": str(machine / "workspaces" / "code"),
            "test_artifacts": str(machine / "artifacts" / "tests"),
            "documents": str(exports / "documents"),
            "reports": str(exports / "reports"),
            "exported_code": str(exports / "code"),
        },
        "iso_inventory": _inventory_iso(machine),
    }


def ensure(*, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise StorageLayoutError("La création de la bibliothèque doit être confirmée.")
    machine, exports = roots()
    validation = validate_machine_root(machine)
    if not validation["valid"]:
        raise StorageLayoutError(" ".join(validation["issues"]))
    for relative in MACHINE_SUBDIRECTORIES:
        (machine / Path(relative)).mkdir(parents=True, exist_ok=True)
    for relative in EXPORT_SUBDIRECTORIES:
        (exports / Path(relative)).mkdir(parents=True, exist_ok=True)
    return status()
