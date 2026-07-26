"""Opérations de mutation du système de fichiers exposées à Marvin."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable


_resolve_path: Callable[[str], str] | None = None


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
