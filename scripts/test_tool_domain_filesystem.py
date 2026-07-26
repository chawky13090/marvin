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
        listing = await filesystem.list_entries({"path": "docs"})
        assert listing["count"] == 1 and listing["files"][0]["category"] == "Texte"
        metadata = await filesystem.info({"path": "docs/a.txt", "hash": True})
        assert metadata["size_bytes"] == 1
        assert len(metadata["md5"]) == 32 and len(metadata["sha256"]) == 64
        read = await filesystem.read({"path": "docs/a.txt"})
        assert read["content"] == "a" and read["content_truncated"] is False
        (base / "docs/data.csv").write_text("name,value\nmarvin,1\n", encoding="utf-8")
        csv_read = await filesystem.read({"path": "docs/data.csv"})
        assert csv_read["rows"] == 2 and "marvin\t1" in csv_read["content"]
        (base / "docs/legacy.xls").write_bytes(b"legacy")
        legacy = await filesystem.read({"path": "docs/legacy.xls"})
        assert legacy["unsupported_format"] is True
        found = await filesystem.find({
            "path": "docs", "pattern": "*.txt", "use_index": False
        })
        assert found["method"] == "os.walk" and found["count"] == 1
        invalid_limit = await filesystem.find({
            "path": "docs", "pattern": "*", "max_results": "many"
        })
        assert "entier attendu" in invalid_limit["error"]
        text_search = await filesystem.search_text({
            "path": "docs", "query": "marvin", "extensions": "csv"
        })
        assert text_search["count"] == 1
        assert text_search["candidate_limit_reached"] is False
        missing_search = await filesystem.search_text({
            "path": "absent", "query": "marvin"
        })
        assert "introuvable" in missing_search["error"]
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
    assert tools.execute_file_list is filesystem.list_entries
    assert tools.execute_file_info is filesystem.info
    assert tools.execute_file_read is filesystem.read
    assert tools.execute_file_find is filesystem.find
    assert tools.execute_file_search_text is filesystem.search_text
    assert tools.execute_file_delete is filesystem.delete
    assert tools.execute_file_rename is filesystem.rename
    assert tools.execute_file_move is filesystem.move
    assert tools.execute_file_copy is filesystem.copy
    assert tools.execute_file_create_folder is filesystem.create_folder
    print("Tool Domain Filesystem OK - mutations, collisions, confirmation et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
