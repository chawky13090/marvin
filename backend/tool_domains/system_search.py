"""Recherche de fichiers et de contenu via l'index Windows Search."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import Any

PathNormalizer = Callable[[str], str]
QueryRunner = Callable[[str, PathNormalizer], list[dict[str, Any]]]

_NAME_TYPES = {"", "all", "folder", "file", "pdf", "docx", "xlsx", "image"}
_CONTENT_TYPES = {"", "all", "pdf", "docx", "xlsx", "text"}


def _bounded_limit(value: Any, default: int) -> int:
    try:
        return max(1, min(int(value), 100))
    except (TypeError, ValueError):
        return default


def _com_query(sql: str, normalize_path: PathNormalizer) -> list[dict[str, Any]]:
    import pythoncom
    import win32com.client

    com_initialized = False
    connection = None
    recordset = None
    try:
        pythoncom.CoInitialize()
        com_initialized = True
        connection = win32com.client.Dispatch("ADODB.Connection")
        connection.Open(
            "Provider=Search.CollatorDSO;Extended Properties='Application=Windows';"
        )
        recordset = win32com.client.Dispatch("ADODB.Recordset")
        recordset.Open(sql, connection)
        results: list[dict[str, Any]] = []
        content_search = "System.Search.AutoSummary" in sql
        while not recordset.EOF:
            path = recordset.Fields("System.ItemPathDisplay").Value
            path = normalize_path(str(path)) if path else ""
            name = recordset.Fields("System.ItemName").Value

            def field(name_: str, default: Any = "") -> Any:
                try:
                    return recordset.Fields(name_).Value or default
                except Exception:
                    return default

            try:
                size = max(0, int(field("System.Size", 0)))
            except (TypeError, ValueError):
                size = 0
            item = {
                "name": str(name) if name else "",
                "path": path,
                "size": size,
                "size_kb": round(size / 1024, 1) if size else 0,
                "extension": str(field("System.FileExtension")),
                "modified": str(field("System.DateModified")),
            }
            if content_search:
                item["snippet"] = " ".join(
                    str(field("System.Search.AutoSummary")).split()
                )[:280]
            else:
                item["is_dir"] = str(field("System.ItemType")) == "Directory"
            results.append(item)
            recordset.MoveNext()
        return results
    finally:
        if recordset is not None:
            try:
                recordset.Close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.Close()
            except Exception:
                pass
        if com_initialized:
            pythoncom.CoUninitialize()


async def search(
    args: dict[str, Any],
    *,
    normalize_path: PathNormalizer,
    query_runner: QueryRunner = _com_query,
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    file_type = str(args.get("file_type") or "").strip().lower()
    if not query and not file_type:
        return {"error": "Paramètre 'query' requis, ou indiquez un 'file_type'."}
    if file_type not in _NAME_TYPES:
        return {"error": f"Type de fichier non pris en charge : {file_type}"}
    limit = _bounded_limit(args.get("max_results"), 30)
    pattern = "%" if not query else (
        query if any(char in query for char in "*?%") else f"%{query}%"
    )
    sql_pattern = pattern.replace("*", "%").replace("?", "_").replace("'", "''")
    where = [f"System.FileName LIKE '{sql_pattern}'"]
    filters = {
        "folder": "System.ItemType = 'Directory'",
        "file": "System.ItemType <> 'Directory'",
        "pdf": "System.FileExtension = '.pdf'",
        "docx": "(System.FileExtension = '.docx' OR System.FileExtension = '.doc')",
        "xlsx": (
            "(System.FileExtension = '.xlsx' OR System.FileExtension = '.xls' "
            "OR System.FileExtension = '.csv')"
        ),
        "image": (
            "(System.FileExtension = '.jpg' OR System.FileExtension = '.jpeg' "
            "OR System.FileExtension = '.png' OR System.FileExtension = '.gif' "
            "OR System.FileExtension = '.webp')"
        ),
    }
    if file_type in filters:
        where.append(filters[file_type])
    sql = (
        f"SELECT TOP {limit} System.ItemPathDisplay, System.ItemName, System.Size, "
        "System.DateModified, System.ItemType, System.FileExtension "
        f"FROM SystemIndex WHERE {' AND '.join(where)} "
        "ORDER BY System.DateModified DESC"
    )
    started = time.monotonic()
    try:
        results = await asyncio.to_thread(query_runner, sql, normalize_path)
    except ImportError:
        return {"error": "win32com indisponible. Installez le paquet pywin32."}
    except Exception as exc:
        return {
            "error": f"Erreur Windows Search : {str(exc)[:200]}. "
            "Vérifiez que le service 'Windows Search' est démarré."
        }
    return {
        "success": True,
        "query": query,
        "file_type": file_type or "all",
        "count": len(results),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "method": "windows_search_index",
        "results": results,
        "hint": (
            "Pour voir le contenu d'un dossier trouvé, utilisez file_list avec son chemin."
            if results
            else "Aucun résultat. Vérifiez les Options d'indexation de Windows Search."
        ),
    }


async def search_content(
    args: dict[str, Any],
    *,
    normalize_path: PathNormalizer,
    query_runner: QueryRunner = _com_query,
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    file_type = str(args.get("file_type") or "").strip().lower()
    if not query:
        return {"error": "Paramètre 'query' requis pour la recherche par contenu."}
    if file_type not in _CONTENT_TYPES:
        return {"error": f"Type de fichier non pris en charge : {file_type}"}
    limit = _bounded_limit(args.get("max_results"), 25)
    words = [word for word in re.findall(r"\w+", query, re.UNICODE) if len(word) > 1]
    terms = " AND ".join(f'"{word}*"' for word in words) if words else f'"{query}"'
    terms = terms.replace("'", "''")
    where = [f"CONTAINS(System.Search.Contents, '{terms}')"]
    filters = {
        "pdf": "System.FileExtension = '.pdf'",
        "docx": "(System.FileExtension = '.docx' OR System.FileExtension = '.doc')",
        "xlsx": (
            "(System.FileExtension = '.xlsx' OR System.FileExtension = '.xls' "
            "OR System.FileExtension = '.csv')"
        ),
        "text": (
            "(System.FileExtension = '.txt' OR System.FileExtension = '.md' "
            "OR System.FileExtension = '.log')"
        ),
    }
    if file_type in filters:
        where.append(filters[file_type])
    sql = (
        f"SELECT TOP {limit} System.ItemPathDisplay, System.ItemName, System.Size, "
        "System.DateModified, System.FileExtension, System.Search.AutoSummary "
        f"FROM SystemIndex WHERE {' AND '.join(where)} "
        "ORDER BY System.DateModified DESC"
    )
    started = time.monotonic()
    try:
        results = await asyncio.to_thread(query_runner, sql, normalize_path)
    except ImportError:
        return {"error": "win32com indisponible. Installez le paquet pywin32."}
    except Exception as exc:
        return {
            "error": f"Erreur Windows Search (contenu) : {str(exc)[:200]}. "
            "Le service 'Windows Search' doit être démarré."
        }
    return {
        "success": True,
        "query": query,
        "file_type": file_type or "all",
        "count": len(results),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "method": "windows_search_content",
        "results": results,
        "hint": (
            "Vous pouvez indexer un résultat avec document_index pour l'interroger."
            if results
            else "Aucun document correspondant, ou emplacement non indexé."
        ),
    }
