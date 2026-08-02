"""Inspection déterministe de la provenance du runtime Python de Marvin."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


SUPPORTED_MINIMUM = (3, 12)
SUPPORTED_MAXIMUM_EXCLUSIVE = (3, 14)
_EPHEMERAL_MARKERS = (
    "\\.cache\\codex-runtimes\\",
    "\\appdata\\local\\temp\\",
    "\\windowsapps\\python.exe",
    "\\windowsapps\\python3.exe",
)


def _normalized(path: str | os.PathLike[str] | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, TypeError, ValueError):
        return str(path)


def is_ephemeral_path(path: str | os.PathLike[str] | None) -> bool:
    normalized = _normalized(path).casefold()
    return any(marker in normalized for marker in _EPHEMERAL_MARKERS)


def read_pyvenv_config(venv_root: str | os.PathLike[str] | None = None) -> dict[str, str]:
    root = Path(venv_root) if venv_root else Path(sys.prefix)
    config_path = root / "pyvenv.cfg"
    values: dict[str, str] = {}
    try:
        for raw_line in config_path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = raw_line.partition("=")
            if separator:
                values[key.strip().casefold()] = value.strip()
    except OSError:
        pass
    return values


def inspect_runtime(
    *,
    executable: str | os.PathLike[str] | None = None,
    base_executable: str | os.PathLike[str] | None = None,
    venv_root: str | os.PathLike[str] | None = None,
    version_info: tuple[int, int] | None = None,
) -> dict[str, Any]:
    current_executable = _normalized(executable or sys.executable)
    current_base = _normalized(base_executable or getattr(sys, "_base_executable", sys.executable))
    version = version_info or (sys.version_info.major, sys.version_info.minor)
    config = read_pyvenv_config(venv_root)
    configured_home = _normalized(config.get("home"))
    configured_executable = _normalized(config.get("executable"))
    reasons: list[str] = []

    if not (SUPPORTED_MINIMUM <= version < SUPPORTED_MAXIMUM_EXCLUSIVE):
        reasons.append("unsupported_version")
    if not current_base or not Path(current_base).is_file():
        reasons.append("base_executable_missing")
    observed_paths = [current_executable, current_base, configured_home, configured_executable]
    if any(is_ephemeral_path(path) for path in observed_paths if path):
        reasons.append("ephemeral_runtime")

    portable = not reasons
    return {
        "schema_version": 1,
        "status": "available" if portable else "degraded",
        "portable": portable,
        "version": f"{version[0]}.{version[1]}",
        "executable": current_executable,
        "base_executable": current_base,
        "configured_home": configured_home,
        "configured_executable": configured_executable,
        "reasons": reasons,
    }
