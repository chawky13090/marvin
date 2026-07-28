"""Recherche fédérée bornée avec provenance et erreurs par source."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any


AsyncSearch = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
VectorSearch = Callable[..., Awaitable[list[dict[str, Any]]]]
MemoryRecall = Callable[..., Awaitable[dict[str, Any]]]

DEFAULT_SOURCES = (
    "documents",
    "files_name",
    "files_content",
    "notes",
    "tasks",
    "events",
    "memory",
)
ALL_SOURCES = DEFAULT_SOURCES + ("emails", "web")
_MAX_QUERY_LENGTH = 1_000
_MAX_CONCURRENCY = 4
_SOURCE_TIMEOUT_SECONDS = 45.0

_vector_search: VectorSearch | None = None
_system_search: AsyncSearch | None = None
_system_search_content: AsyncSearch | None = None
_list_notes: Callable[..., list[dict[str, Any]]] | None = None
_list_tasks: Callable[..., list[dict[str, Any]]] | None = None
_list_events: Callable[..., list[dict[str, Any]]] | None = None
_memory_recall: MemoryRecall | None = None
_email_search: AsyncSearch | None = None
_web_search: AsyncSearch | None = None


def configure(
    *,
    vector_search: VectorSearch,
    system_search: AsyncSearch,
    system_search_content: AsyncSearch,
    list_notes: Callable[..., list[dict[str, Any]]],
    list_tasks: Callable[..., list[dict[str, Any]]],
    list_events: Callable[..., list[dict[str, Any]]],
    memory_recall: MemoryRecall,
    email_search: AsyncSearch,
    web_search: AsyncSearch,
) -> None:
    global _vector_search, _system_search, _system_search_content
    global _list_notes, _list_tasks, _list_events
    global _memory_recall, _email_search, _web_search
    _vector_search = vector_search
    _system_search = system_search
    _system_search_content = system_search_content
    _list_notes = list_notes
    _list_tasks = list_tasks
    _list_events = list_events
    _memory_recall = memory_recall
    _email_search = email_search
    _web_search = web_search


def _dependencies() -> tuple[
    VectorSearch,
    AsyncSearch,
    AsyncSearch,
    Callable[..., list[dict[str, Any]]],
    Callable[..., list[dict[str, Any]]],
    Callable[..., list[dict[str, Any]]],
    MemoryRecall,
    AsyncSearch,
    AsyncSearch,
]:
    values = (
        _vector_search,
        _system_search,
        _system_search_content,
        _list_notes,
        _list_tasks,
        _list_events,
        _memory_recall,
        _email_search,
        _web_search,
    )
    if any(value is None for value in values):
        raise RuntimeError("Le domaine de recherche unifiée n'est pas configuré.")
    return values  # type: ignore[return-value]


def _validate_args(args: dict[str, Any]) -> tuple[str, list[str], int, str | None]:
    raw_query = args.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise ValueError("Indique ce que tu cherches (paramètre 'query').")
    query = raw_query.strip()
    if len(query) > _MAX_QUERY_LENGTH:
        raise ValueError(f"'query' est limitée à {_MAX_QUERY_LENGTH} caractères.")

    raw_scope = args.get("scope")
    if raw_scope is None or raw_scope == "":
        requested = list(DEFAULT_SOURCES)
    elif isinstance(raw_scope, str):
        requested = [raw_scope]
    elif isinstance(raw_scope, list) and all(
        isinstance(item, str) for item in raw_scope
    ):
        requested = raw_scope
    else:
        raise ValueError("'scope' doit être une chaîne ou une liste de chaînes.")

    normalized = [item.strip().casefold() for item in requested if item.strip()]
    if "all" in normalized:
        normalized = list(ALL_SOURCES)
    invalid = sorted({item for item in normalized if item not in ALL_SOURCES})
    if invalid:
        raise ValueError(
            "Sources inconnues : "
            + ", ".join(invalid)
            + ". Sources valides : "
            + ", ".join(ALL_SOURCES)
            + "."
        )
    scope = list(dict.fromkeys(normalized))
    if not scope:
        raise ValueError("'scope' ne peut pas être vide.")

    raw_limit = args.get("limit", 5)
    if isinstance(raw_limit, bool):
        raise ValueError("'limit' doit être un entier entre 1 et 15.")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("'limit' doit être un entier entre 1 et 15.") from exc
    if not 1 <= limit <= 15:
        raise ValueError("'limit' doit être un entier entre 1 et 15.")

    raw_account = args.get("account")
    if raw_account is not None and not isinstance(raw_account, str):
        raise ValueError("'account' doit être une chaîne.")
    account = raw_account.strip() if isinstance(raw_account, str) else None
    if account and len(account) > 320:
        raise ValueError("'account' est limité à 320 caractères.")
    return query, scope, limit, account or None


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


async def search(args: dict[str, Any]) -> dict[str, Any]:
    """Interroge explicitement les sources demandées avec budgets et provenance."""
    try:
        query, scope, per_source, account = _validate_args(args)
        (
            vector_search,
            system_search,
            system_search_content,
            list_notes,
            list_tasks,
            list_events,
            memory_recall,
            email_search,
            web_search,
        ) = _dependencies()
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}

    query_folded = query.casefold()

    async def documents() -> list[dict[str, Any]]:
        hits = await vector_search(
            query, collections=["documents"], limit=per_source
        )
        return [
            {
                "name": (hit.get("metadata") or {}).get("name", "?"),
                "snippet": _text(hit.get("text"), 200),
                "path": (hit.get("metadata") or {}).get("path"),
                "score": round(float(hit.get("score") or 0), 3),
            }
            for hit in hits[:per_source]
            if isinstance(hit, dict)
        ]

    async def files_name() -> list[dict[str, Any]]:
        result = await system_search(
            {"query": query, "max_results": per_source}
        )
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "is_dir": item.get("is_dir"),
                "size_kb": item.get("size_kb"),
            }
            for item in (result.get("results") or [])[:per_source]
            if isinstance(item, dict)
        ]

    async def files_content() -> list[dict[str, Any]]:
        result = await system_search_content(
            {"query": query, "max_results": per_source}
        )
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "snippet": _text(item.get("snippet"), 300),
            }
            for item in (result.get("results") or [])[:per_source]
            if isinstance(item, dict)
        ]

    async def notes() -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            list_notes, search=query, limit=per_source
        )
        return [
            {
                "id": note.get("id"),
                "title": note.get("title"),
                "snippet": _text(note.get("content"), 160),
            }
            for note in rows[:per_source]
            if isinstance(note, dict)
        ]

    async def tasks() -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(list_tasks, limit=200)
        output: list[dict[str, Any]] = []
        for task in rows:
            if not isinstance(task, dict):
                continue
            haystack = (
                f"{task.get('title', '')} {task.get('description') or ''}"
            ).casefold()
            if query_folded in haystack:
                output.append(
                    {
                        "id": task.get("id"),
                        "title": task.get("title"),
                        "status": task.get("status"),
                        "priority": task.get("priority"),
                        "due_date": task.get("due_date"),
                    }
                )
            if len(output) >= per_source:
                break
        return output

    async def events() -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(list_events, limit=400)
        output: list[dict[str, Any]] = []
        for event in rows:
            if not isinstance(event, dict):
                continue
            haystack = (
                f"{event.get('title', '')} {event.get('description') or ''} "
                f"{event.get('location') or ''}"
            ).casefold()
            if query_folded in haystack:
                output.append(
                    {
                        "id": event.get("id"),
                        "title": event.get("title"),
                        "start_at": event.get("start_at"),
                        "location": event.get("location"),
                        "source": event.get("source"),
                    }
                )
            if len(output) >= per_source:
                break
        return output

    async def memory() -> list[dict[str, Any]]:
        recalled = await memory_recall(query, max_facts=per_source, max_qa=3)
        items = [
            {"type": "fait", "text": _text(fact, 500)}
            for fact in recalled.get("facts", [])
        ]
        items.extend(
            {
                "type": "q/r",
                "text": _text(f"{item.get('q', '')} → {item.get('a', '')}", 800),
            }
            for item in recalled.get("qa", [])
            if isinstance(item, dict)
        )
        return items[:per_source]

    async def emails() -> list[dict[str, Any]]:
        result = await email_search({"query": query, "account": account})
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return [
            {
                "subject": item.get("subject"),
                "from": item.get("from") or item.get("from_addr"),
                "date": item.get("date"),
                "uid": item.get("uid"),
            }
            for item in (result.get("emails") or [])[:per_source]
            if isinstance(item, dict)
        ]

    async def web() -> list[dict[str, Any]]:
        result = await web_search(
            {"query": query, "max_results": per_source}
        )
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        return [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": _text(
                    item.get("snippet") or item.get("description"), 200
                ),
            }
            for item in (result.get("results") or [])[:per_source]
            if isinstance(item, dict)
        ]

    functions: Mapping[str, Callable[[], Awaitable[list[dict[str, Any]]]]] = {
        "documents": documents,
        "files_name": files_name,
        "files_content": files_content,
        "notes": notes,
        "tasks": tasks,
        "events": events,
        "memory": memory,
        "emails": emails,
        "web": web,
    }
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def run_source(source: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        started = time.perf_counter()
        try:
            async with semaphore:
                items = await asyncio.wait_for(
                    functions[source](), timeout=_SOURCE_TIMEOUT_SECONDS
                )
            return items, {
                "status": "ok",
                "count": len(items),
                "ms": int((time.perf_counter() - started) * 1_000),
            }
        except TimeoutError:
            return [], {
                "status": "timeout",
                "count": 0,
                "ms": int((time.perf_counter() - started) * 1_000),
                "error": f"Délai dépassé ({_SOURCE_TIMEOUT_SECONDS:g} s).",
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return [], {
                "status": "error",
                "count": 0,
                "ms": int((time.perf_counter() - started) * 1_000),
                "error": str(exc)[:200],
            }

    gathered = await asyncio.gather(*(run_source(source) for source in scope))
    results = {
        source: outcome[0] for source, outcome in zip(scope, gathered)
    }
    source_status = {
        source: outcome[1] for source, outcome in zip(scope, gathered)
    }
    errors = {
        source: status["error"]
        for source, status in source_status.items()
        if status["status"] != "ok"
    }
    total = sum(len(items) for items in results.values())
    successful_sources = sum(
        1 for status in source_status.values() if status["status"] == "ok"
    )
    return {
        "success": True,
        "query": query,
        "scope": scope,
        "total": total,
        "results": results,
        "source_status": source_status,
        "errors": errors or None,
        "policy": {
            "max_concurrency": _MAX_CONCURRENCY,
            "source_timeout_seconds": _SOURCE_TIMEOUT_SECONDS,
            "per_source_limit": per_source,
        },
        "message": (
            f"{total} résultat(s) pour « {query} »; "
            f"{successful_sources}/{len(scope)} source(s) interrogée(s) sans erreur."
        ),
    }
