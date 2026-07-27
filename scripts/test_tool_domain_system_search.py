"""Régressions déterministes du domaine Windows Search."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import system_search


async def main() -> None:
    captured: list[str] = []

    def fake_runner(sql: str, normalize_path):
        captured.append(sql)
        return [
            {
                "name": "rapport.pdf",
                "path": normalize_path(r"C:\Users\Chawb\Documents\rapport.pdf"),
                "size": 1024,
            }
        ]

    result = await system_search.search(
        {"query": "l'été", "file_type": "pdf", "max_results": 500},
        normalize_path=lambda path: path,
        query_runner=fake_runner,
    )
    assert result["success"] is True
    assert result["count"] == 1
    assert "TOP 100" in captured[-1]
    assert "l''été" in captured[-1]
    assert "System.FileExtension = '.pdf'" in captured[-1]

    content = await system_search.search_content(
        {"query": "contrat support", "file_type": "text", "max_results": "2"},
        normalize_path=lambda path: path,
        query_runner=fake_runner,
    )
    assert content["success"] is True
    assert 'CONTAINS(System.Search.Contents, \'"contrat*" AND "support*"\')' in captured[-1]
    assert "TOP 2" in captured[-1]

    invalid = await system_search.search(
        {"query": "x", "file_type": "exe"},
        normalize_path=lambda path: path,
        query_runner=fake_runner,
    )
    assert "error" in invalid
    missing = await system_search.search_content(
        {"query": ""},
        normalize_path=lambda path: path,
        query_runner=fake_runner,
    )
    assert "error" in missing
    assert tools.TOOLS_REGISTRY["system_search"] is tools.execute_system_search
    assert tools.TOOLS_REGISTRY["system_search_content"] is tools.execute_system_search_content


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - domaine Windows Search")
