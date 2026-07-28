"""Régressions du nettoyage système borné et isolé."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import system_cleanup


def _format_bytes(value: int) -> str:
    return f"{value} B"


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-cleanup-") as temporary:
        root = Path(temporary)
        old_file = root / "old.tmp"
        recent_file = root / "recent.tmp"
        nested_file = root / "nested" / "old.log"
        nested_file.parent.mkdir()
        old_file.write_bytes(b"a" * 10)
        recent_file.write_bytes(b"b" * 20)
        nested_file.write_bytes(b"c" * 30)
        old_timestamp = time.time() - (3 * 86_400)
        os.utime(old_file, (old_timestamp, old_timestamp))
        os.utime(nested_file, (old_timestamp, old_timestamp))

        system_cleanup.configure(
            candidate_paths=lambda: [root, root, root / "missing"],
            format_bytes=_format_bytes,
        )
        report = await system_cleanup.cleanup({"min_age_days": 1})
        assert report["success"] is True
        assert report["total_files"] == 3
        assert report["reclaimable_files"] == 2
        assert report["reclaimable_human"] == "40 B"
        assert report["deleted"] is False
        assert old_file.exists() and recent_file.exists() and nested_file.exists()
        assert len(report["locations"]) == 1

        limited = await system_cleanup.cleanup(
            {"min_age_days": 0, "max_files": 1}
        )
        assert limited["total_files"] == 1
        assert limited["truncated"] is True
        assert "1 dossier temporaire inspecté" in limited["message"]

        deleted = await system_cleanup.cleanup(
            {"min_age_days": 1, "delete": True}
        )
        assert deleted["freed_files"] == 2
        assert deleted["freed_human"] == "40 B"
        assert not old_file.exists() and not nested_file.exists()
        assert recent_file.exists()

        assert "min_age_days" in (
            await system_cleanup.cleanup({"min_age_days": -1})
        )["error"]
        assert "max_files" in (
            await system_cleanup.cleanup({"max_files": 500_001})
        )["error"]

    system_cleanup.configure(
        candidate_paths=tools._system_cleanup_candidates,
        format_bytes=tools._fmt_bytes,
    )
    assert tools.execute_system_cleanup is system_cleanup.cleanup
    assert tools.TOOLS_REGISTRY["system_cleanup"] is system_cleanup.cleanup


if __name__ == "__main__":
    asyncio.run(main())
    print("System Cleanup OK - âge, bornes, suppression isolée et façade.")
