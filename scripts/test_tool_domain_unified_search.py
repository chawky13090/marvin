"""Régressions de la recherche fédérée, ses bornes et sa provenance."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database
import learning
import tools
import vector_store
from tool_domains import unified_search


async def vector_search(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
    return [
        {
            "metadata": {"name": "Guide", "path": "C:/Guide.txt"},
            "text": "Marvin est documenté",
            "score": 0.98765,
        }
    ]


async def system_search(_args: dict[str, Any]) -> dict[str, Any]:
    return {"results": [{"name": "Marvin", "path": "C:/Marvin"}]}


async def system_search_content(_args: dict[str, Any]) -> dict[str, Any]:
    return {"error": "index indisponible"}


async def memory_recall(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    return {"facts": ["Marvin local"], "qa": [{"q": "Qui ?", "a": "Marvin"}]}


async def email_search(_args: dict[str, Any]) -> dict[str, Any]:
    return {"emails": [{"subject": "Marvin", "from": "test@example.invalid"}]}


async def web_search(_args: dict[str, Any]) -> dict[str, Any]:
    return {"results": [{"title": "Marvin", "url": "https://example.invalid"}]}


def configure_fakes() -> None:
    unified_search.configure(
        vector_search=vector_search,
        system_search=system_search,
        system_search_content=system_search_content,
        list_notes=lambda **_kwargs: [
            {"id": "n1", "title": "Marvin", "content": "Note Marvin"}
        ],
        list_tasks=lambda **_kwargs: [
            {
                "id": "t1",
                "title": "Tester Marvin",
                "description": "",
                "status": "pending",
            }
        ],
        list_events=lambda **_kwargs: [
            {"id": "e1", "title": "Marvin", "description": "", "location": ""}
        ],
        memory_recall=memory_recall,
        email_search=email_search,
        web_search=web_search,
    )


async def main() -> None:
    configure_fakes()
    default = await unified_search.search({"query": "Marvin", "limit": 2})
    assert default["success"] is True
    assert default["scope"] == list(unified_search.DEFAULT_SOURCES)
    assert default["source_status"]["files_content"]["status"] == "error"
    assert default["errors"]["files_content"] == "index indisponible"
    assert default["results"]["documents"][0]["score"] == 0.988
    assert "emails" not in default["results"]
    assert "web" not in default["results"]
    assert default["policy"]["max_concurrency"] == 4

    all_sources = await unified_search.search(
        {"query": "Marvin", "scope": ["all"], "limit": 1}
    )
    assert all_sources["scope"] == list(unified_search.ALL_SOURCES)
    assert all_sources["results"]["emails"][0]["subject"] == "Marvin"
    assert all_sources["results"]["web"][0]["url"] == "https://example.invalid"

    assert "Sources inconnues" in (
        await unified_search.search({"query": "Marvin", "scope": ["inconnue"]})
    )["error"]
    assert "entier" in (
        await unified_search.search({"query": "Marvin", "limit": "abc"})
    )["error"]
    assert "1000" in (
        await unified_search.search({"query": "x" * 1_001})
    )["error"]

    original_timeout = unified_search._SOURCE_TIMEOUT_SECONDS
    try:
        async def slow_search(_args: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(0.05)
            return {"results": []}

        unified_search._SOURCE_TIMEOUT_SECONDS = 0.01
        unified_search.configure(
            vector_search=vector_search,
            system_search=slow_search,
            system_search_content=system_search_content,
            list_notes=lambda **_kwargs: [],
            list_tasks=lambda **_kwargs: [],
            list_events=lambda **_kwargs: [],
            memory_recall=memory_recall,
            email_search=email_search,
            web_search=web_search,
        )
        timed_out = await unified_search.search(
            {"query": "Marvin", "scope": ["files_name"]}
        )
        assert timed_out["source_status"]["files_name"]["status"] == "timeout"
    finally:
        unified_search._SOURCE_TIMEOUT_SECONDS = original_timeout

    unified_search.configure(
        vector_search=vector_store.search,
        system_search=tools.execute_system_search,
        system_search_content=tools.execute_system_search_content,
        list_notes=database.list_notes,
        list_tasks=database.list_tasks,
        list_events=database.list_events,
        memory_recall=learning.recall,
        email_search=tools.execute_email_search,
        web_search=tools.execute_web_search,
    )
    assert tools.execute_unified_search is unified_search.search
    assert tools.TOOLS_REGISTRY["unified_search"] is unified_search.search


if __name__ == "__main__":
    asyncio.run(main())
    print("Unified search OK - scopes, provenance, erreurs, timeout et façade.")
