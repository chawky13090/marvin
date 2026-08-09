"""Opérations de mutation du système de fichiers exposées à Marvin."""

from __future__ import annotations

import os
import shutil
import hashlib
import time
import csv
import io
import re
import asyncio
import codecs
import fnmatch
import heapq
import json
import uuid
from pathlib import Path
from typing import Any, Callable

import regex as safe_regex


_resolve_path: Callable[[str], str] | None = None
_normalize_index_path: Callable[[str], str] | None = None
_MAX_CONTENT = 50_000
_SEARCH_TEXT_EXTENSIONS = (
    ".txt", ".md", ".pdf", ".docx", ".csv", ".xlsx", ".json",
    ".py", ".js", ".ts", ".html", ".xml", ".log",
)


def configure(
    *,
    resolve_path: Callable[[str], str],
    normalize_index_path: Callable[[str], str] | None = None,
) -> None:
    global _resolve_path, _normalize_index_path
    _resolve_path = resolve_path
    _normalize_index_path = normalize_index_path


def _resolve(raw: str) -> str:
    if _resolve_path is None:
        raise RuntimeError("Le domaine filesystem n'est pas configuré")
    return _resolve_path(raw)


def dedupe_path(destination: str) -> str:
    path = Path(destination)
    if not path.exists():
        return destination
    for index in range(2, 10_002):
        candidate = path.parent / f"{path.stem} ({index}){path.suffix}"
        if not candidate.exists():
            return str(candidate)
    raise FileExistsError("Impossible de trouver un nom de destination libre")


def normalize_destination(source: str, destination: str) -> str:
    source_path = Path(source)
    destination_path = Path(destination)
    if destination_path.is_dir():
        destination_path /= source_path.name
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    return str(destination_path)


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("o", "Ko", "Mo", "Go"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} To"


def extension_category(name: str) -> str:
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    categories = {
        "pdf": "PDF", "doc": "Word", "docx": "Word",
        "xls": "Excel", "xlsx": "Excel", "ppt": "PPT", "pptx": "PPT",
        "txt": "Texte", "md": "Markdown", "csv": "CSV",
        "jpg": "Image", "jpeg": "Image", "png": "Image", "gif": "Image",
        "webp": "Image", "bmp": "Image", "svg": "Image",
        "mp3": "Audio", "wav": "Audio", "flac": "Audio",
        "mp4": "Vidéo", "mkv": "Vidéo", "avi": "Vidéo",
        "zip": "Archive", "rar": "Archive", "7z": "Archive",
        "py": "Python", "js": "JavaScript", "ts": "TypeScript",
        "html": "HTML", "css": "CSS", "json": "JSON", "xml": "XML",
        "exe": "Exécutable", "bat": "Script", "ps1": "PowerShell",
    }
    return categories.get(extension, extension.upper() if extension else "—")


async def list_entries(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    show_hidden = bool(args.get("show_hidden", False))
    try:
        offset = max(0, int(args.get("offset", 0)))
        limit = int(args.get("limit", 100))
    except (TypeError, ValueError):
        return {"error": "Paramètres 'offset' et 'limit' invalides : entiers attendus."}
    if not 1 <= limit <= 1_000:
        return {"error": "Le paramètre 'limit' doit être compris entre 1 et 1 000."}
    try:
        directory = Path(path)
        if not directory.exists():
            return {"error": f"Chemin introuvable : {path}"}
        if not directory.is_dir():
            return {"error": f"Ce n'est pas un répertoire : {path}"}
        try:
            items = sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        except PermissionError:
            return {"error": f"Accès refusé par Windows : {path}. Ce dossier est protégé par le système."}
        entries: list[dict[str, Any]] = []
        for item in items:
            if not show_hidden and item.name.startswith("."):
                continue
            try:
                stat = item.stat()
                is_file = item.is_file()
                size = stat.st_size if is_file else 0
                entries.append({
                    "name": item.name,
                    "type": "fichier" if is_file else "dossier",
                    "category": extension_category(item.name) if is_file else "Dossier",
                    "size": format_size(size) if is_file else "—",
                    "size_bytes": size,
                    "path": str(item),
                    "modified": time.strftime("%d/%m/%Y %H:%M", time.localtime(stat.st_mtime)),
                })
            except (PermissionError, OSError):
                entries.append({
                    "name": item.name,
                    "type": "fichier" if item.is_file() else "dossier",
                    "category": "🔒 Accès refusé",
                    "size": "—",
                    "size_bytes": 0,
                    "path": str(item),
                    "modified": "",
                })
        total_count = len(entries)
        page = entries[offset:offset + limit]
        next_offset = offset + len(page)
        return {
            "success": True,
            "currentDir": str(directory),
            "count": len(page),
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": next_offset < total_count,
            "next_offset": next_offset if next_offset < total_count else None,
            "files": page,
        }
    except Exception as exc:
        return {"error": str(exc)}


async def info(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    if not path:
        return {"error": "Paramètre 'path' requis."}
    try:
        target = Path(path)
        if not target.exists():
            return {"error": f"Introuvable : {path}"}
        stat = target.stat()
        result: dict[str, Any] = {
            "success": True,
            "path": str(target),
            "name": target.name,
            "type": "dossier" if target.is_dir() else "fichier",
            "extension": target.suffix.lower() if target.is_file() else "",
            "created": time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(stat.st_ctime)),
            "modified": time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(stat.st_mtime)),
            "accessed": time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(stat.st_atime)),
        }
        if target.is_file():
            result["size"] = format_size(stat.st_size)
            result["size_bytes"] = stat.st_size
            if args.get("hash", False):
                md5 = hashlib.md5(usedforsecurity=False)
                sha256 = hashlib.sha256()
                with target.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(65_536), b""):
                        md5.update(chunk)
                        sha256.update(chunk)
                result["md5"] = md5.hexdigest()
                result["sha256"] = sha256.hexdigest()
        else:
            try:
                children = list(target.iterdir())
                result["children_count"] = len(children)
                result["files_count"] = sum(1 for child in children if child.is_file())
                result["folders_count"] = sum(1 for child in children if child.is_dir())
            except PermissionError:
                result["children_count"] = "accès refusé"
        return result
    except Exception as exc:
        return {"error": str(exc)}


def _content_result(path: Path, content: str, **extra: Any) -> dict[str, Any]:
    return {
        "success": True,
        "path": str(path),
        "content": content[:_MAX_CONTENT],
        "content_truncated": len(content) > _MAX_CONTENT,
        **extra,
    }


def _read_mission_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        workspace_base = (
            Path(__file__).resolve().parents[2] / "data" / "coding_workspaces"
        ).resolve()
        relative = path.resolve(strict=False).relative_to(workspace_base)
        parts = relative.parts
        if (
            len(parts) < 3
            or not re.fullmatch(r"[0-9a-f]{32}", parts[0], re.IGNORECASE)
            or parts[1].casefold() != "repo"
        ):
            return None
        import coding_mission

        mission_id = parts[0]
        artifact_path = Path(*parts[2:]).as_posix()
        files = coding_mission.latest_files(mission_id)
        if artifact_path not in files:
            return None
        content = files[artifact_path]
        return {
            **_content_result(Path(artifact_path), content),
            "requested_path": str(path),
            "source": "mission_snapshot",
            "mission_id": mission_id,
            "note": (
                "Livrable refusé lu depuis le dernier snapshot; "
                "il n'est pas encore appliqué au worktree."
            ),
        }
    except (ImportError, OSError, ValueError):
        return None


async def read(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    try:
        target = Path(path)
        if not target.exists():
            snapshot = _read_mission_snapshot(target)
            return snapshot or {"error": f"Fichier introuvable : {path}"}
        if not target.is_file():
            return {"error": f"Ce n'est pas un fichier : {path}"}
        extension = target.suffix.lower()

        if extension == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(target))
                content = "\n".join(page.extract_text() or "" for page in reader.pages)
                return _content_result(target, content, pages=len(reader.pages))
            except Exception as exc:
                return {"error": f"Erreur lecture PDF : {exc}"}

        if extension == ".doc":
            return {
                "error": (
                    "Le format Word binaire .doc n'est pas pris en charge par python-docx. "
                    "Convertissez le fichier en .docx avant lecture."
                ),
                "unsupported_format": True,
            }
        if extension == ".docx":
            try:
                from docx import Document

                document = Document(str(target))
                content = "\n".join(paragraph.text for paragraph in document.paragraphs)
                return _content_result(target, content)
            except Exception as exc:
                return {"error": f"Erreur lecture Word : {exc}"}

        if extension == ".xls":
            return {
                "error": (
                    "Le format Excel binaire .xls n'est pas pris en charge par openpyxl. "
                    "Convertissez le classeur en .xlsx avant lecture."
                ),
                "unsupported_format": True,
            }
        if extension == ".xlsx":
            workbook = None
            try:
                import openpyxl

                workbook = openpyxl.load_workbook(
                    str(target), read_only=True, data_only=True
                )
                sheet_names = list(workbook.sheetnames)
                lines: list[str] = []
                for sheet_name in sheet_names:
                    worksheet = workbook[sheet_name]
                    lines.append(f"=== Feuille : {sheet_name} ===")
                    for row in worksheet.iter_rows(values_only=True):
                        if any(cell is not None for cell in row):
                            lines.append("\t".join(
                                str(cell) if cell is not None else "" for cell in row
                            ))
                return _content_result(target, "\n".join(lines), sheets=sheet_names)
            except Exception as exc:
                return {"error": f"Erreur lecture Excel : {exc}"}
            finally:
                if workbook is not None:
                    workbook.close()

        if extension == ".csv":
            try:
                raw = None
                for encoding in ("utf-8", "latin-1", "cp1252"):
                    try:
                        raw = target.read_text(encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                if raw is None:
                    raw = target.read_bytes().decode(errors="replace")
                lines = ["\t".join(row) for row in csv.reader(io.StringIO(raw))]
                return _content_result(target, "\n".join(lines), rows=len(lines))
            except Exception as exc:
                return {"error": f"Erreur lecture CSV : {exc}"}

        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                return _content_result(target, target.read_text(encoding=encoding))
            except UnicodeDecodeError:
                continue
        return {"error": "Encodage non supporté"}
    except Exception as exc:
        return {"error": str(exc)}


def _windows_index_search(
    pattern: str,
    max_results: int,
    path_filter: str | None,
) -> list[dict[str, Any]] | None:
    try:
        import pythoncom
        import win32com.client as win32com
    except ImportError:
        return None
    initialized = False
    connection = None
    recordset = None
    try:
        pythoncom.CoInitialize()
        initialized = True
        sql_pattern = pattern.replace("*", "%").replace("?", "_")
        if not sql_pattern.startswith("%") and not any(
            character in sql_pattern for character in "%_"
        ):
            sql_pattern = f"%{sql_pattern}%"
        sql_pattern = sql_pattern.replace("'", "''")
        where = [f"System.FileName LIKE '{sql_pattern}'"]
        if path_filter:
            scope = path_filter.replace("'", "''").replace("\\", "/")
            where.append(f"SCOPE='file:{scope}'")
        query = (
            f"SELECT TOP {max_results} System.ItemPathDisplay, System.ItemName, "
            "System.Size, System.DateModified, System.ItemType "
            f"FROM SystemIndex WHERE {' AND '.join(where)}"
        )
        connection = win32com.Dispatch("ADODB.Connection")
        connection.Open(
            "Provider=Search.CollatorDSO;"
            "Extended Properties='Application=Windows';"
        )
        recordset = win32com.Dispatch("ADODB.Recordset")
        recordset.Open(query, connection)
        results: list[dict[str, Any]] = []
        while not recordset.EOF:
            def field(name: str, default: Any = None) -> Any:
                try:
                    return recordset.Fields(name).Value
                except Exception:
                    return default

            path_value = field("System.ItemPathDisplay", "")
            normalized_path = (
                _normalize_index_path(str(path_value or ""))
                if _normalize_index_path is not None
                else str(path_value or "")
            )
            size_value = field("System.Size", 0)
            try:
                size_value = int(size_value or 0)
            except (TypeError, ValueError):
                size_value = 0
            results.append({
                "name": str(field("System.ItemName", "") or ""),
                "path": normalized_path,
                "size": size_value,
                "modified": str(field("System.DateModified", "") or ""),
                "type": str(field("System.ItemType", "") or ""),
            })
            recordset.MoveNext()
        return results
    except Exception:
        return None
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
        if initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _walk_search(
    root: str,
    pattern: str,
    include_dirs: bool,
    max_results: int,
) -> tuple[list[dict[str, Any]], int]:
    results: list[dict[str, Any]] = []
    scanned = 0
    excluded = {
        "$RECYCLE.BIN", "System Volume Information", "AppData", "node_modules",
        "__pycache__", ".git", ".venv", "Windows.old", "Windows",
        "Program Files", "Program Files (x86)",
    }
    for directory, dirs, files in os.walk(root):
        dirs[:] = [
            name for name in dirs
            if not name.startswith(".") and name not in excluded
        ]
        for name in files + (dirs if include_dirs else []):
            scanned += 1
            if not fnmatch.fnmatch(name.casefold(), pattern.casefold()):
                continue
            full_path = os.path.join(directory, name)
            try:
                stat = os.stat(full_path)
                results.append({
                    "name": name,
                    "path": full_path,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
            except OSError:
                results.append({"name": name, "path": full_path})
            if len(results) >= max_results:
                return results, scanned
    return results, scanned


def _normalize_index_results(
    results: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if results is None or _normalize_index_path is None:
        return results
    return [
        {
            **item,
            "path": _normalize_index_path(str(item.get("path", ""))),
        }
        for item in results
    ]


def _shallow_scan(root: str, pattern: str, include_dirs: bool, max_results: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with os.scandir(root) as entries:
        for entry in entries:
            if not fnmatch.fnmatch(entry.name.casefold(), pattern.casefold()):
                continue
            if entry.is_dir() and not include_dirs:
                continue
            try:
                stat = entry.stat()
                results.append({
                    "name": entry.name,
                    "path": entry.path,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "type": "Directory" if entry.is_dir() else Path(entry.name).suffix or "",
                })
            except OSError:
                results.append({"name": entry.name, "path": entry.path})
            if len(results) >= max_results:
                break
    return results


async def find(args: dict[str, Any]) -> dict[str, Any]:
    pattern = str(args.get("pattern", "*")).strip()
    path = str(args.get("path", "")).strip()
    if not pattern:
        return {"error": "Paramètre 'pattern' requis. Ex: *.pdf, rapport*, *abdou*"}
    try:
        max_results = max(1, min(1000, int(args.get("max_results", 100))))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'max_results' invalide : entier attendu."}
    include_dirs = bool(args.get("include_dirs", False))
    use_index = bool(args.get("use_index", True))
    recursive = bool(args.get("recursive", True))
    global_scope = not path or path.casefold() in {"all", "tout", "everywhere", "*"}

    # v2.537 — Incident réel reproduit (conversation « Liste des éléments du bureau ») :
    # `pattern="*"` recursait dans TOUS les sous-dossiers et plafonnait à 500 résultats
    # sans distinguer le contenu direct du dossier demandé de celui de ses sous-dossiers
    # — impossible d'obtenir une liste propre et complète du premier niveau. `recursive`
    # (par défaut `true`, rétrocompatible) permet un scan superficiel non tronqué.
    if not recursive:
        resolved = Path(_resolve(path or "~"))
        if not resolved.exists() or not resolved.is_dir():
            return {"error": f"Dossier introuvable : {resolved}"}
        results = await asyncio.to_thread(
            _shallow_scan, str(resolved), pattern, include_dirs, max_results
        )
        return {
            "success": True,
            "pattern": pattern,
            "root": str(resolved),
            "method": "shallow_scan",
            "recursive": False,
            "count": len(results),
            "results": results,
        }

    if use_index and global_scope:
        results = _normalize_index_results(await asyncio.to_thread(
            _windows_index_search, pattern, max_results, None
        ))
        if results is not None:
            return {
                "success": True,
                "pattern": pattern,
                "method": "windows_search_index",
                "scope": "all indexed locations",
                "count": len(results),
                "results": results,
            }
        path = "~"
    resolved = Path(_resolve(path or "~"))
    if not resolved.exists() or not resolved.is_dir():
        return {"error": f"Dossier introuvable : {resolved}"}
    if use_index:
        results = _normalize_index_results(await asyncio.to_thread(
            _windows_index_search, pattern, max_results, str(resolved)
        ))
        if results:
            return {
                "success": True,
                "pattern": pattern,
                "root": str(resolved),
                "method": "windows_search_index",
                "count": len(results),
                "results": results,
            }
    results, scanned = await asyncio.to_thread(
        _walk_search, str(resolved), pattern, include_dirs, max_results
    )
    return {
        "success": True,
        "pattern": pattern,
        "root": str(resolved),
        "method": "os.walk",
        "count": len(results),
        "scanned": scanned,
        "results": results,
    }


def _normalize_extensions(raw: Any) -> set[str]:
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, (list, tuple, set)):
        values = _SEARCH_TEXT_EXTENSIONS
    normalized = set()
    for value in values:
        extension = str(value).strip().casefold()
        if not extension:
            continue
        normalized.add(extension if extension.startswith(".") else f".{extension}")
    return normalized or set(_SEARCH_TEXT_EXTENSIONS)


def _collect_candidates(
    directory: str,
    extensions: set[str],
    max_files: int,
) -> tuple[list[Path], int, bool]:
    candidates: list[Path] = []
    visited = 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [
            name for name in dirs
            if not name.startswith(".")
            and name not in {".git", ".venv", "node_modules", "__pycache__"}
        ]
        for filename in files:
            visited += 1
            path = Path(root) / filename
            if path.suffix.casefold() in extensions:
                candidates.append(path)
                if len(candidates) >= max_files:
                    return candidates, visited, True
    return candidates, visited, False


async def search_text(args: dict[str, Any]) -> dict[str, Any]:
    directory = Path(_resolve(str(
        args.get("directory") or args.get("path") or ""
    )))
    query = str(args.get("query", ""))
    if not query:
        return {"error": "Requête de recherche vide"}
    if not directory.exists() or not directory.is_dir():
        return {"error": f"Dossier introuvable : {directory}"}
    try:
        max_results = max(1, min(1000, int(args.get("max_results", 20))))
        max_files = max(1, min(50_000, int(args.get("max_files", 5000))))
    except (TypeError, ValueError):
        return {
            "error": (
                "Paramètres 'max_results' ou 'max_files' invalides : "
                "entiers attendus."
            )
        }
    extensions = _normalize_extensions(
        args.get("extensions", _SEARCH_TEXT_EXTENSIONS)
    )
    case_sensitive = bool(args.get("case_sensitive", False))
    needle = query if case_sensitive else query.casefold()
    try:
        candidates, visited, limited = await asyncio.to_thread(
            _collect_candidates, str(directory), extensions, max_files
        )
        results: list[dict[str, str]] = []
        read_errors = 0
        for path in candidates:
            if len(results) >= max_results:
                break
            content_result = await read({"path": str(path)})
            text = content_result.get("content", "")
            if not text:
                if content_result.get("error"):
                    read_errors += 1
                continue
            haystack = text if case_sensitive else text.casefold()
            index = haystack.find(needle)
            if index < 0:
                continue
            start = max(0, index - 80)
            end = min(len(text), index + len(query) + 80)
            results.append({
                "name": path.name,
                "path": str(path),
                "snippet": f"...{text[start:end].strip()}...",
            })
        return {
            "success": True,
            "query": query,
            "directory": str(directory),
            "count": len(results),
            "results": results,
            "files_visited": visited,
            "candidates_read": min(len(candidates), max_files),
            "read_errors": read_errors,
            "candidate_limit_reached": limited,
        }
    except Exception as exc:
        return {"error": str(exc)}


async def write(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    content = str(args.get("content", ""))
    append = bool(args.get("append", False) or args.get("mode") == "append")
    try:
        target = Path(path)
        if not append and args.get("overwrite") is False:
            target = Path(dedupe_path(str(target)))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if append else "w", encoding="utf-8") as stream:
            stream.write(content)
        action = "complété" if append else "écrit"
        return {
            "success": True,
            "message": f"Fichier {action} : {target}",
            "path": str(target),
        }
    except Exception as exc:
        return {"error": str(exc)}


async def delete(args: dict[str, Any]) -> dict[str, Any]:
    # v2.524 — Par défaut, "supprimer" envoie vers la Corbeille Windows : une
    # confirmation de chat ne devrait jamais être irréversible quand un repli
    # existe. `permanent=True` (demandé explicitement) garde l'ancien
    # comportement, avec un message de confirmation qui le dit sans ambiguïté.
    permanent = bool(args.get("permanent"))
    if not args.get("confirmed"):
        verb = "définitivement" if permanent else "vers la Corbeille"
        return {
            "requiresConfirmation": True,
            "message": f"Supprimer {verb} : {args.get('path', '')} ?",
        }
    path = _resolve(str(args.get("path", "")))
    target = Path(path)
    if not target.exists():
        return {"error": f"Introuvable : {path}"}
    if not permanent:
        try:
            import send2trash
            await asyncio.to_thread(send2trash.send2trash, str(target))
            return {
                "success": True,
                "message": f"Envoyé à la Corbeille : {path}",
                "permanent": False,
            }
        except ModuleNotFoundError:
            return {
                "error": "Corbeille indisponible (dépendance 'send2trash' absente). "
                         "Relancer avec permanent=true pour une suppression définitive.",
            }
        except Exception as exc:
            # Un chemin réseau/amovible peut refuser la Corbeille (pas de bac local).
            # On NE bascule PAS silencieusement en suppression définitive : on
            # informe et on laisse l'appelant redemander avec permanent=True.
            return {
                "error": f"Envoi à la Corbeille impossible ({exc}). "
                         "Relancer avec permanent=true pour une suppression définitive.",
            }
    try:
        shutil.rmtree(target) if target.is_dir() else target.unlink()
        return {"success": True, "message": f"Supprimé définitivement : {path}", "permanent": True}
    except Exception as exc:
        return {"error": str(exc)}


async def rename(args: dict[str, Any]) -> dict[str, Any]:
    source = _resolve(str(args.get("source", "")))
    raw_destination = args.get("destination") or args.get("new_name") or ""
    if not raw_destination:
        return {"error": "Paramètre 'destination' ou 'new_name' requis."}
    destination = (
        str(Path(source).parent / str(raw_destination))
        if not any(char in str(raw_destination) for char in ("/", "\\"))
        else _resolve(str(raw_destination))
    )
    try:
        source_path = Path(source)
        if not source_path.exists():
            return {"error": f"Source introuvable : {source}"}
        if Path(destination).exists():
            return {"error": f"Destination déjà existante : {destination}"}
        source_path.rename(destination)
        return {
            "success": True,
            "message": f"Renommé : {source_path.name} → {Path(destination).name}",
            "old_path": source,
            "new_path": destination,
        }
    except Exception as exc:
        return {"error": str(exc)}


async def move(args: dict[str, Any]) -> dict[str, Any]:
    return await _transfer(args, copy=False)


async def copy(args: dict[str, Any]) -> dict[str, Any]:
    return await _transfer(args, copy=True)


async def _transfer(args: dict[str, Any], *, copy: bool) -> dict[str, Any]:
    source = _resolve(str(args.get("source", "")))
    destination = _resolve(str(args.get("destination", "")))
    source_path = Path(source)
    if not source_path.exists():
        return {"error": f"Source introuvable : {source}"}
    try:
        destination = normalize_destination(source, destination)
        same_path = os.path.normcase(os.path.abspath(source)) == os.path.normcase(
            os.path.abspath(destination)
        )
        if same_path and not copy:
            return {"error": "La source et la destination sont identiques."}
        if same_path or Path(destination).exists():
            destination = dedupe_path(destination)
        if copy:
            shutil.copytree(source, destination) if source_path.is_dir() else shutil.copy2(source, destination)
        else:
            shutil.move(source, destination)
        verb = "Copié" if copy else "Déplacé"
        return {
            "success": True,
            "message": f"{verb} : {source} → {destination}",
            "destination": destination,
        }
    except Exception as exc:
        return {"error": str(exc)}


async def create_folder(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return {"success": True, "message": f"Dossier créé : {path}", "path": path}
    except Exception as exc:
        return {"error": str(exc)}


def _format_bytes_precise(size: int) -> str:
    value = float(size)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "o" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} Po"


def _walk_files(root: Path, maximum: int):
    count = 0
    excluded = {"$recycle.bin", "system volume information", ".git", "node_modules"}
    for directory, directories, files in os.walk(root, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if name.casefold() not in excluded
            and not Path(directory, name).is_symlink()
        ]
        for name in files:
            if count >= maximum:
                return
            path = Path(directory, name)
            if path.is_symlink():
                continue
            count += 1
            yield path


def _large_files_scan(
    root: Path, top: int, threshold: int, max_files: int
) -> tuple[list[tuple[int, str]], int, bool]:
    heap: list[tuple[int, str]] = []
    scanned = 0
    for path in _walk_files(root, max_files + 1):
        if scanned >= max_files:
            return sorted(heap, reverse=True), scanned, True
        scanned += 1
        try:
            size = path.stat().st_size
        except OSError:
            continue
        candidate = (size, str(path))
        if size >= threshold:
            if len(heap) < top:
                heapq.heappush(heap, candidate)
            elif size > heap[0][0]:
                heapq.heapreplace(heap, candidate)
    return sorted(heap, reverse=True), scanned, False


async def large_finder(args: dict[str, Any]) -> dict[str, Any]:
    directory = str(args.get("directory") or args.get("path") or "~")
    try:
        root = Path(_resolve(directory))
        if not root.is_dir():
            return {"error": f"Dossier introuvable : {root}"}
        top = int(args.get("top", 20))
        min_mb = float(args.get("min_mb", 0))
        max_files = int(args.get("max_files", 100_000))
        if not 1 <= top <= 500:
            raise ValueError("'top' doit être compris entre 1 et 500.")
        if not 0 <= min_mb <= 1_000_000:
            raise ValueError("'min_mb' doit être compris entre 0 et 1 000 000.")
        if not 1 <= max_files <= 1_000_000:
            raise ValueError("'max_files' doit être compris entre 1 et 1 000 000.")
        items, scanned, truncated = await asyncio.to_thread(
            _large_files_scan,
            root,
            top,
            int(min_mb * 1024 * 1024),
            max_files,
        )
        total = sum(size for size, _ in items)
        return {
            "success": True,
            "directory": str(root),
            "count": len(items),
            "scanned": scanned,
            "scan_truncated": truncated,
            "total_human": _format_bytes_precise(total),
            "files": [
                {
                    "path": path,
                    "size_bytes": size,
                    "size_human": _format_bytes_precise(size),
                }
                for size, path in items
            ],
            "message": f"{len(items)} plus gros fichiers ({_format_bytes_precise(total)})",
        }
    except (OSError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


def _batch_read_sync(
    paths: list[str], max_chars: int, encoding: str
) -> tuple[list[dict[str, Any]], int]:
    results: list[dict[str, Any]] = []
    total_chars = 0
    for raw_path in paths:
        resolved = _resolve(raw_path.strip())
        entry: dict[str, Any] = {"path": resolved, "success": False}
        try:
            path = Path(resolved)
            if not path.is_file():
                raise FileNotFoundError(path)
            with path.open(encoding=encoding, errors="replace") as stream:
                content = stream.read(max_chars + 1)
            truncated = len(content) > max_chars
            content = content[:max_chars]
            entry.update(
                {
                    "success": True,
                    "content": content,
                    "chars": len(content),
                    "truncated": truncated,
                }
            )
            total_chars += len(content)
        except FileNotFoundError:
            entry["error"] = "Fichier introuvable"
        except (OSError, UnicodeError, ValueError) as exc:
            entry["error"] = str(exc)
        results.append(entry)
    return results, total_chars


async def batch_read(args: dict[str, Any]) -> dict[str, Any]:
    paths = args.get("paths", [])
    if isinstance(paths, str):
        paths = [part.strip() for part in paths.split(",") if part.strip()]
    if not isinstance(paths, list) or not paths:
        return {"error": "Paramètre 'paths' requis (liste de chemins de fichiers)."}
    if len(paths) > 20 or not all(isinstance(path, str) and path.strip() for path in paths):
        return {"error": "'paths' doit contenir entre 1 et 20 chemins non vides."}
    try:
        max_chars = int(args.get("max_chars_per_file", 5_000))
        if not 1 <= max_chars <= 100_000:
            raise ValueError("'max_chars_per_file' doit être compris entre 1 et 100 000.")
        encoding = str(args.get("encoding") or "utf-8").strip()
        codecs.lookup(encoding)
        results, total_chars = await asyncio.to_thread(
            _batch_read_sync, paths, max_chars, encoding
        )
        return {
            "success": True,
            "files_read": sum(bool(item.get("success")) for item in results),
            "files_error": sum(bool(item.get("error")) for item in results),
            "total_chars": total_chars,
            "files": results,
        }
    except (LookupError, TypeError, ValueError) as exc:
        return {"error": f"Paramètres de lecture invalides : {exc}"}


def _duplicate_scan(root: Path, min_size: int, max_files: int) -> dict[str, Any]:
    by_size: dict[int, list[Path]] = {}
    scanned = 0
    truncated = False
    for path in _walk_files(root, max_files + 1):
        if scanned >= max_files:
            truncated = True
            break
        scanned += 1
        try:
            size = path.stat().st_size
            if size >= min_size:
                by_size.setdefault(size, []).append(path)
        except OSError:
            continue
    duplicates: list[dict[str, Any]] = []
    wasted = 0
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_digest: dict[str, list[str]] = {}
        for path in paths:
            try:
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                by_digest.setdefault(digest, []).append(str(path))
            except OSError:
                continue
        for digest, matches in by_digest.items():
            if len(matches) > 1:
                duplicates.append(
                    {
                        "sha256": digest,
                        "size_kb": round(size / 1024, 1),
                        "count": len(matches),
                        "files": matches,
                    }
                )
                wasted += size * (len(matches) - 1)
    duplicates.sort(
        key=lambda item: item["size_kb"] * item["count"], reverse=True
    )
    return {
        "scanned": scanned,
        "scan_truncated": truncated,
        "duplicates": duplicates,
        "total_wasted": wasted,
    }


async def duplicate_finder(args: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    root = Path(_resolve(raw_path))
    if not root.is_dir():
        return {"error": f"Dossier introuvable : {root}"}
    try:
        min_size_kb = int(args.get("min_size_kb", 10))
        max_files = int(args.get("max_files", 5_000))
        if not 0 <= min_size_kb <= 1_000_000_000:
            raise ValueError("'min_size_kb' doit être positif et borné.")
        if not 1 <= max_files <= 1_000_000:
            raise ValueError("'max_files' doit être compris entre 1 et 1 000 000.")
        scan = await asyncio.to_thread(
            _duplicate_scan, root, min_size_kb * 1024, max_files
        )
        duplicates = scan["duplicates"]
        return {
            "success": True,
            "root": str(root),
            "scanned": scan["scanned"],
            "scan_truncated": scan["scan_truncated"],
            "duplicate_groups": len(duplicates),
            "wasted_space_mb": round(scan["total_wasted"] / 1024**2, 1),
            "duplicates": duplicates[:50],
            "groups_truncated": len(duplicates) > 50,
            "hash_algorithm": "sha256-full",
            "hint": "Empreinte SHA-256 du fichier complet. Vérifiez avant toute suppression.",
        }
    except (OSError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_filename(name: str) -> str:
    if (
        not name
        or name in {".", ".."}
        or Path(name).name != name
        or any(character in name for character in '<>:"/\\|?*\0')
        or name.endswith((" ", "."))
    ):
        raise ValueError(f"Nom de destination invalide : {name!r}")
    stem = name.split(".", 1)[0].casefold()
    if stem in {
        "con", "prn", "aux", "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }:
        raise ValueError(f"Nom réservé par Windows : {name!r}")
    return name


def _load_rename_manifest(raw_path: str) -> tuple[Path, dict[str, Any], Path]:
    manifest_path = Path(_resolve(raw_path)).resolve()
    if not manifest_path.is_file() or manifest_path.suffix.lower() != ".json":
        raise ValueError(f"Manifeste de rollback introuvable : {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or payload.get("tool") != "bulk_rename":
        raise ValueError("Manifeste bulk_rename invalide ou incompatible.")
    root = Path(str(payload.get("root") or "")).resolve()
    expected_parent = (root / ".marvin-rollback").resolve()
    if manifest_path.parent != expected_parent:
        raise ValueError("Le manifeste doit appartenir au dossier .marvin-rollback de la cible.")
    operations = payload.get("operations")
    if not root.is_dir() or not isinstance(operations, list) or not operations:
        raise ValueError("Le manifeste ne contient aucune opération valide.")
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Opération de rollback invalide.")
        for key in ("old", "new", "temporary"):
            operation[key] = _validate_filename(str(operation.get(key) or ""))
    return manifest_path, payload, root


def _restore_rename_operations(root: Path, operations: list[dict[str, str]]) -> None:
    to_restore: list[dict[str, str]] = []
    for operation in operations:
        old = root / operation["old"]
        new = root / operation["new"]
        temporary = root / operation["temporary"]
        if old.exists():
            if new.exists() or temporary.exists():
                raise FileExistsError(
                    f"Rollback ambigu : {old.name!r} existe avec une autre copie."
                )
            continue
        if new.exists() and temporary.exists():
            raise FileExistsError(
                f"Rollback ambigu : cible et temporaire existent pour {old.name!r}."
            )
        if not new.exists() and not temporary.exists():
            raise FileNotFoundError(
                f"Rollback impossible : état absent pour {old.name!r}."
            )
        to_restore.append(operation)

    moved_to_temporary: list[dict[str, str]] = []
    try:
        for operation in to_restore:
            new = root / operation["new"]
            temporary = root / operation["temporary"]
            if new.exists():
                new.rename(temporary)
                moved_to_temporary.append(operation)
        restored: list[dict[str, str]] = []
        try:
            for operation in reversed(to_restore):
                temporary = root / operation["temporary"]
                old = root / operation["old"]
                temporary.rename(old)
                restored.append(operation)
        except OSError:
            for operation in reversed(restored):
                old = root / operation["old"]
                temporary = root / operation["temporary"]
                if old.exists() and not temporary.exists():
                    old.rename(temporary)
            raise
    except OSError:
        for operation in reversed(moved_to_temporary):
            temporary = root / operation["temporary"]
            new = root / operation["new"]
            if temporary.exists() and not new.exists():
                temporary.rename(new)
        raise


def _apply_bulk_rename(
    root: Path,
    operations: list[dict[str, str]],
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    _atomic_json(manifest_path, manifest)
    staged: list[dict[str, str]] = []
    try:
        for operation in operations:
            (root / operation["old"]).rename(root / operation["temporary"])
            staged.append(operation)
        for operation in operations:
            (root / operation["temporary"]).rename(root / operation["new"])
        manifest["status"] = "applied"
        manifest["applied_at"] = time.time()
        _atomic_json(manifest_path, manifest)
    except OSError:
        try:
            _restore_rename_operations(root, operations)
            manifest["status"] = "rolled_back_after_failure"
        except OSError as rollback_error:
            manifest["status"] = "recovery_required"
            manifest["recovery_error"] = str(rollback_error)
        manifest["failed_at"] = time.time()
        _atomic_json(manifest_path, manifest)
        raise


async def bulk_rename(args: dict[str, Any]) -> dict[str, Any]:
    """Planifie, applique ou annule un renommage transactionnel dans un dossier."""
    action = str(args.get("action") or "").strip().lower()
    rollback_manifest = str(args.get("rollback_manifest") or "").strip()
    if rollback_manifest or action == "rollback":
        if not rollback_manifest:
            return {"error": "'rollback_manifest' est requis pour l'action rollback."}
        if not args.get("confirmed"):
            return {
                "requiresConfirmation": True,
                "message": f"Restaurer les noms depuis : {rollback_manifest} ?",
            }
        try:
            manifest_path, manifest, root = _load_rename_manifest(rollback_manifest)
            if manifest.get("status") == "rolled_back":
                return {
                    "success": True,
                    "folder": str(root),
                    "restored": 0,
                    "already_rolled_back": True,
                    "rollback_manifest": str(manifest_path),
                }
            await asyncio.to_thread(
                _restore_rename_operations, root, manifest["operations"]
            )
            manifest["status"] = "rolled_back"
            manifest["rolled_back_at"] = time.time()
            await asyncio.to_thread(_atomic_json, manifest_path, manifest)
            return {
                "success": True,
                "folder": str(root),
                "restored": len(manifest["operations"]),
                "rollback_manifest": str(manifest_path),
                "rollback_available": False,
            }
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"error": str(exc), "rollback_manifest": rollback_manifest}

    folder = str(args.get("folder") or "").strip()
    pattern = str(args.get("pattern") or "").strip()
    replacement = str(args.get("replace") or "")
    glob_pattern = str(args.get("glob") or "*").strip()
    if not folder:
        return {"error": "Paramètre 'folder' requis."}
    if not pattern:
        return {"error": "Paramètre 'pattern' requis."}
    if len(pattern) > 1_000 or len(replacement) > 1_000 or len(glob_pattern) > 255:
        return {"error": "Motif, remplacement ou filtre trop long."}
    if any(separator in glob_pattern for separator in ("/", "\\")):
        return {"error": "Le filtre glob ne doit pas contenir de chemin."}
    try:
        root = Path(_resolve(folder)).resolve()
        if not root.is_dir():
            return {"error": f"Dossier introuvable : {root}"}
        expression = safe_regex.compile(pattern)
        files = sorted(
            (
                path
                for path in root.iterdir()
                if path.is_file() and not path.is_symlink()
                and fnmatch.fnmatch(path.name, glob_pattern)
            ),
            key=lambda path: path.name.casefold(),
        )
        if len(files) > 5_000:
            raise ValueError("Le renommage en lot est limité à 5 000 fichiers.")
        run_id = uuid.uuid4().hex
        operations: list[dict[str, str]] = []
        for index, source in enumerate(files):
            new_name = expression.sub(replacement, source.name, timeout=0.25)
            if new_name != source.name:
                operations.append(
                    {
                        "old": source.name,
                        "new": _validate_filename(new_name),
                        "temporary": f".marvin-rename-{run_id}-{index}.tmp",
                    }
                )
        if not operations:
            return {
                "success": True,
                "message": "Aucun fichier ne correspond au motif.",
                "renamed": 0,
            }

        source_keys = {operation["old"].casefold() for operation in operations}
        destination_keys: set[str] = set()
        occupied = {
            path.name.casefold()
            for path in root.iterdir()
            if path.name.casefold() not in source_keys
        }
        for operation in operations:
            destination_key = operation["new"].casefold()
            if destination_key in destination_keys:
                raise FileExistsError(
                    f"Plusieurs fichiers produisent la destination {operation['new']!r}."
                )
            if destination_key in occupied:
                raise FileExistsError(
                    f"La destination existe déjà : {operation['new']!r}."
                )
            destination_keys.add(destination_key)
            if (root / operation["temporary"]).exists():
                raise FileExistsError("Nom temporaire déjà utilisé; recommencez l'opération.")

        preview = [
            {
                "old": operation["old"],
                "new": operation["new"],
                "old_path": str(root / operation["old"]),
                "new_path": str(root / operation["new"]),
            }
            for operation in operations
        ]
        if not args.get("confirmed"):
            return {
                "requiresConfirmation": True,
                "message": (
                    f"Renommer {len(operations)} fichier(s) dans {root.name} ?\n"
                    f"Exemple : {operations[0]['old']} → {operations[0]['new']}"
                ),
                "preview": preview[:10],
                "preview_truncated": len(preview) > 10,
            }

        manifest_path = root / ".marvin-rollback" / f"bulk-rename-{run_id}.json"
        manifest = {
            "version": 1,
            "tool": "bulk_rename",
            "status": "planned",
            "created_at": time.time(),
            "root": str(root),
            "operations": operations,
        }
        await asyncio.to_thread(
            _apply_bulk_rename, root, operations, manifest_path, manifest
        )
        return {
            "success": True,
            "folder": str(root),
            "renamed": len(operations),
            "errors": [],
            "files": preview[:50],
            "files_truncated": len(preview) > 50,
            "rollback_available": True,
            "rollback_manifest": str(manifest_path),
        }
    except (
        OSError,
        TypeError,
        ValueError,
        safe_regex.error,
        TimeoutError,
    ) as exc:
        return {"error": str(exc)}
