"""Opérations de mutation du système de fichiers exposées à Marvin."""

from __future__ import annotations

import os
import shutil
import hashlib
import time
import csv
import io
import re
from pathlib import Path
from typing import Any, Callable


_resolve_path: Callable[[str], str] | None = None
_MAX_CONTENT = 50_000


def configure(*, resolve_path: Callable[[str], str]) -> None:
    global _resolve_path
    _resolve_path = resolve_path


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
        return {
            "success": True,
            "currentDir": str(directory),
            "count": len(entries),
            "files": entries,
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


async def write(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    content = str(args.get("content", ""))
    append = bool(args.get("append", False) or args.get("mode") == "append")
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if append else "w", encoding="utf-8") as stream:
            stream.write(content)
        action = "complété" if append else "écrit"
        return {"success": True, "message": f"Fichier {action} : {path}", "path": str(target)}
    except Exception as exc:
        return {"error": str(exc)}


async def delete(args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Supprimer définitivement : {args.get('path', '')} ?",
        }
    path = _resolve(str(args.get("path", "")))
    try:
        target = Path(path)
        if not target.exists():
            return {"error": f"Introuvable : {path}"}
        shutil.rmtree(target) if target.is_dir() else target.unlink()
        return {"success": True, "message": f"Supprimé : {path}"}
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
        return {"success": True, "message": f"Dossier créé : {path}"}
    except Exception as exc:
        return {"error": str(exc)}
