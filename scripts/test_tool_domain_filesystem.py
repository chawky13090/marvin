"""Régressions du domaine de mutation de fichiers et de la façade tools.py."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import filesystem


async def main() -> int:
    with tempfile.TemporaryDirectory() as root:
        base = Path(root)
        filesystem.configure(resolve_path=lambda raw: str(base / raw))
        created = await filesystem.create_folder({"path": "docs"})
        assert created["success"] and (base / "docs").is_dir()
        written = await filesystem.write({"path": "docs/a.txt", "content": "a"})
        assert written["success"]
        await filesystem.write({"path": "docs/a.txt", "content": "b", "mode": "append"})
        assert (base / "docs/a.txt").read_text(encoding="utf-8") == "ab"
        copied = await filesystem.copy({"source": "docs/a.txt", "destination": "docs"})
        assert copied["success"] and copied["destination"].endswith("a (2).txt")
        renamed = await filesystem.rename({"source": "docs/a.txt", "new_name": "b.txt"})
        assert renamed["success"] and (base / "docs/b.txt").exists()
        same = await filesystem.move({"source": "docs/b.txt", "destination": "docs/b.txt"})
        assert "identiques" in same["error"]
        confirmation = await filesystem.delete({"path": "docs/b.txt"})
        assert confirmation["requiresConfirmation"] is True
        deleted = await filesystem.delete({"path": "docs/b.txt", "confirmed": True})
        assert deleted["success"] and not (base / "docs/b.txt").exists()

    filesystem.configure(resolve_path=tools._resolve_path)
    assert tools.execute_file_write is filesystem.write
    assert tools.execute_file_delete is filesystem.delete
    assert tools.execute_file_rename is filesystem.rename
    assert tools.execute_file_move is filesystem.move
    assert tools.execute_file_copy is filesystem.copy
    assert tools.execute_file_create_folder is filesystem.create_folder
    print("Tool Domain Filesystem OK - mutations, collisions, confirmation et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
