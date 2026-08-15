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
        (base / "paged").mkdir()
        for index in range(105):
            (base / "paged" / f"page-{index:03}.txt").write_text("x", encoding="utf-8")
        first_page = await filesystem.list_entries({"path": "paged", "limit": 40})
        assert first_page["count"] == 40
        assert first_page["total_count"] == 105 and first_page["has_more"] is True
        second_page = await filesystem.list_entries({
            "path": "paged", "limit": 40, "offset": first_page["next_offset"]
        })
        assert second_page["offset"] == 40 and second_page["count"] == 40
        last_page = await filesystem.list_entries({"path": "paged", "limit": 40, "offset": 80})
        assert last_page["count"] == 25 and last_page["has_more"] is False
        assert last_page["next_offset"] is None
        invalid_page = await filesystem.list_entries({"path": "paged", "limit": 1001})
        assert "compris entre 1 et 1 000" in invalid_page["error"]
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
        original_index_search = filesystem._windows_index_search
        try:
            filesystem.configure(
                resolve_path=lambda raw: str(base / raw),
                normalize_index_path=lambda raw: raw.replace(
                    r"C:\Utilisateurs\Chawb\Bureau",
                    r"C:\Users\Chawb\Desktop",
                ),
            )
            filesystem._windows_index_search = lambda *_args: [{
                "name": "rapport.pdf",
                "path": r"C:\Utilisateurs\Chawb\Bureau\rapport.pdf",
            }]
            indexed = await filesystem.find({"pattern": "rapport"})
            assert indexed["results"][0]["path"] == (
                r"C:\Users\Chawb\Desktop\rapport.pdf"
            )
        finally:
            filesystem._windows_index_search = original_index_search
            filesystem.configure(resolve_path=lambda raw: str(base / raw))
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
        non_destructive = await filesystem.write(
            {
                "path": "docs/a.txt",
                "content": "nouveau",
                "overwrite": False,
            }
        )
        assert non_destructive["success"] is True
        assert non_destructive["path"].endswith("a (2).txt")
        assert (base / "docs/a.txt").read_text(encoding="utf-8") == "ab"
        assert (base / "docs/a (2).txt").read_text(encoding="utf-8") == "nouveau"
        copied = await filesystem.copy({"source": "docs/a.txt", "destination": "docs"})
        assert copied["success"] and copied["destination"].endswith("a (3).txt")
        renamed = await filesystem.rename({"source": "docs/a.txt", "new_name": "b.txt"})
        assert renamed["success"] and (base / "docs/b.txt").exists()
        same = await filesystem.move({"source": "docs/b.txt", "destination": "docs/b.txt"})
        assert "identiques" in same["error"]
        confirmation = await filesystem.delete({"path": "docs/b.txt"})
        assert confirmation["requiresConfirmation"] is True
        deleted = await filesystem.delete({"path": "docs/b.txt", "confirmed": True})
        assert deleted["success"] and not (base / "docs/b.txt").exists()

        duplicate_payload = ("Marvin vérifie le fichier complet.\n" * 100).encode("utf-8")
        (base / "docs/duplicate-a.bin").write_bytes(duplicate_payload)
        (base / "docs/duplicate-b.bin").write_bytes(duplicate_payload)
        (base / "docs/heavy-folder").mkdir()
        (base / "docs/heavy-folder/payload.bin").write_bytes(b"x" * 4096)
        (base / "docs/same-prefix.bin").write_bytes(
            duplicate_payload[:64] + b"different-tail"
        )
        large = await filesystem.large_finder(
            {"directory": "docs", "top": 2, "min_mb": 0, "max_files": 100}
        )
        assert large["success"] is True and large["count"] == 2
        assert large["scan_truncated"] is False
        assert large["files"][0]["size_bytes"] >= large["files"][1]["size_bytes"]
        assert large["directory_sizes_partial"] is False
        assert large["directories"][0]["path"].endswith("heavy-folder")
        assert large["directories"][0]["size_bytes"] == 4096

        batch = await filesystem.batch_read(
            {
                "paths": ["docs/data.csv", "docs/missing.txt"],
                "max_chars_per_file": 8,
                "encoding": "utf-8",
            }
        )
        assert batch["files_read"] == 1 and batch["files_error"] == 1
        assert batch["files"][0]["content"] == "name,val"
        assert batch["files"][0]["truncated"] is True
        assert "error" in await filesystem.batch_read(
            {"paths": ["docs/data.csv"], "encoding": "not-an-encoding"}
        )

        duplicates = await filesystem.duplicate_finder(
            {"path": "docs", "min_size_kb": 1, "max_files": 100}
        )
        assert duplicates["success"] is True
        assert duplicates["duplicate_groups"] == 1
        assert duplicates["duplicates"][0]["count"] == 2
        assert len(duplicates["duplicates"][0]["sha256"]) == 64
        assert duplicates["hash_algorithm"] == "sha256-full"
        bounded = await filesystem.duplicate_finder(
            {"path": "docs", "min_size_kb": 0, "max_files": 1}
        )
        assert bounded["scan_truncated"] is True

        rename_root = base / "rename"
        rename_root.mkdir()
        (rename_root / "alpha-01.txt").write_text("alpha", encoding="utf-8")
        (rename_root / "beta-02.txt").write_text("beta", encoding="utf-8")
        preview = await filesystem.bulk_rename(
            {
                "folder": "rename",
                "pattern": r"^(.*)-(\d+)\.txt$",
                "replace": r"\1.txt",
                "glob": "*.txt",
            }
        )
        assert preview["requiresConfirmation"] is True
        assert len(preview["preview"]) == 2

        applied = await filesystem.bulk_rename(
            {
                "folder": "rename",
                "pattern": r"^(.*)-(\d+)\.txt$",
                "replace": r"\1.txt",
                "glob": "*.txt",
                "confirmed": True,
            }
        )
        assert applied["success"] is True and applied["renamed"] == 2
        assert applied["rollback_available"] is True
        manifest_path = Path(applied["rollback_manifest"])
        assert manifest_path.is_file()
        assert (rename_root / "alpha.txt").is_file()
        assert (rename_root / "beta.txt").is_file()

        manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
        first = manifest["operations"][0]
        (rename_root / first["new"]).rename(rename_root / first["temporary"])
        rolled_back = await filesystem.bulk_rename(
            {
                "action": "rollback",
                "rollback_manifest": str(manifest_path),
                "confirmed": True,
            }
        )
        assert rolled_back["success"] is True and rolled_back["restored"] == 2
        assert (rename_root / "alpha-01.txt").is_file()
        assert (rename_root / "beta-02.txt").is_file()
        repeated = await filesystem.bulk_rename(
            {
                "action": "rollback",
                "rollback_manifest": str(manifest_path),
                "confirmed": True,
            }
        )
        assert repeated["already_rolled_back"] is True

        collision_root = base / "collision"
        collision_root.mkdir()
        (collision_root / "a-1.txt").write_text("a", encoding="utf-8")
        (collision_root / "a-2.txt").write_text("b", encoding="utf-8")
        collision = await filesystem.bulk_rename(
            {
                "folder": "collision",
                "pattern": r"-\d+",
                "replace": "",
                "confirmed": True,
            }
        )
        assert "Plusieurs fichiers" in collision["error"]
        assert (collision_root / "a-1.txt").is_file()
        assert (collision_root / "a-2.txt").is_file()

    filesystem.configure(
        resolve_path=tools._resolve_path,
        normalize_index_path=tools._normalize_windows_path,
    )
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
    assert tools.execute_file_large_finder is filesystem.large_finder
    assert tools.execute_file_batch_read is filesystem.batch_read
    assert tools.execute_file_duplicate_finder is filesystem.duplicate_finder
    assert tools.execute_bulk_rename is filesystem.bulk_rename
    assert "bulk_rename" in tools.DANGEROUS_TOOLS
    print("Tool Domain Filesystem OK - mutations, collisions, confirmation et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
