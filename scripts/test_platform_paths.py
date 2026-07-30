"""Regression checks for portable Windows Known Folder resolution."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import platform_paths


def main() -> int:
    paths = platform_paths.system_paths()
    required = {
        "home", "desktop", "documents", "downloads", "pictures", "music", "videos",
        "appdata_roaming", "appdata_local", "temp", "startup", "username", "drive",
    }
    assert required.issubset(paths)
    assert all(isinstance(paths[key], str) and paths[key] for key in required - {"drive"})
    assert platform_paths.expand_user_path("Bureau") == platform_paths.PATHS["desktop"]
    assert platform_paths.expand_user_path("Bureau\\rapport.txt") == str(
        Path(platform_paths.PATHS["desktop"]) / "rapport.txt"
    )
    assert platform_paths.expand_user_path("Documents") == platform_paths.PATHS["documents"]
    assert platform_paths.expand_user_path("~") == platform_paths.PATHS["home"]
    drives = platform_paths.logical_drives()
    assert drives and all(isinstance(item, str) and item for item in drives)
    previous = os.environ.get("MARVIN_PATH_TEST")
    try:
        os.environ["MARVIN_PATH_TEST"] = platform_paths.PATHS["temp"]
        assert platform_paths.expand_user_path("%MARVIN_PATH_TEST%") == platform_paths.PATHS["temp"]
    finally:
        if previous is None:
            os.environ.pop("MARVIN_PATH_TEST", None)
        else:
            os.environ["MARVIN_PATH_TEST"] = previous
    source = (ROOT / "backend" / "mcp_server.py").read_text(encoding="utf-8")
    assert "C:\\\\Users\\\\Chawb" not in source
    print("Platform Paths OK - Known Folders, redirections, aliases et variables d'environnement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
