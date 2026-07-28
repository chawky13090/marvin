"""Analyse et nettoyage bornés des répertoires temporaires autorisés."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


_candidate_paths: Callable[[], Iterable[str | os.PathLike[str]]] | None = None
_format_bytes: Callable[[int], str] | None = None
_MAX_FILES = 500_000


def configure(
    *,
    candidate_paths: Callable[[], Iterable[str | os.PathLike[str]]],
    format_bytes: Callable[[int], str],
) -> None:
    global _candidate_paths, _format_bytes
    _candidate_paths = candidate_paths
    _format_bytes = format_bytes


def _dependencies() -> tuple[
    Callable[[], Iterable[str | os.PathLike[str]]],
    Callable[[int], str],
]:
    if _candidate_paths is None or _format_bytes is None:
        raise RuntimeError("Le domaine de nettoyage système n'est pas configuré.")
    return _candidate_paths, _format_bytes


def _normalized_candidates(
    provider: Callable[[], Iterable[str | os.PathLike[str]]],
) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for raw_path in provider():
        if not raw_path:
            continue
        try:
            path = Path(raw_path).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not path.is_dir():
            continue
        identity = os.path.normcase(str(path))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(path)
    return candidates


def _scan_directory(
    root: Path,
    *,
    cutoff: float,
    delete: bool,
    remaining_files: int,
) -> dict[str, Any]:
    total_size = total_files = 0
    reclaimable_size = reclaimable_files = 0
    freed = freed_files = errors = 0
    truncated = False
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            errors += 1
            continue
        for entry in entries:
            if total_files >= remaining_files:
                truncated = True
                stack.clear()
                break
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat(follow_symlinks=False)
                total_files += 1
                total_size += stat.st_size
                if stat.st_mtime >= cutoff:
                    continue
                reclaimable_files += 1
                reclaimable_size += stat.st_size
                if delete:
                    try:
                        os.remove(entry.path)
                    except OSError:
                        errors += 1
                    else:
                        freed += stat.st_size
                        freed_files += 1
            except OSError:
                errors += 1
    return {
        "total_size": total_size,
        "total_files": total_files,
        "reclaimable_size": reclaimable_size,
        "reclaimable_files": reclaimable_files,
        "freed": freed,
        "freed_files": freed_files,
        "errors": errors,
        "truncated": truncated,
    }


def _scan(
    candidates: list[Path],
    *,
    cutoff: float,
    delete: bool,
    max_files: int,
) -> dict[str, Any]:
    report: list[dict[str, Any]] = []
    totals = {
        "total_size": 0,
        "total_files": 0,
        "reclaimable_size": 0,
        "reclaimable_files": 0,
        "freed": 0,
        "freed_files": 0,
        "errors": 0,
    }
    truncated = False
    for root in candidates:
        remaining = max_files - totals["total_files"]
        if remaining <= 0:
            truncated = True
            break
        result = _scan_directory(
            root,
            cutoff=cutoff,
            delete=delete,
            remaining_files=remaining,
        )
        for key in totals:
            totals[key] += int(result[key])
        report.append({"dir": str(root), **result})
        if result["truncated"]:
            truncated = True
            break
    return {"report": report, **totals, "truncated": truncated}


async def cleanup(args: dict) -> dict:
    """Analyse ou supprime les seuls fichiers temporaires assez anciens."""
    candidate_provider, format_bytes = _dependencies()
    try:
        min_age_days = float(args.get("min_age_days", 1))
        if not 0 <= min_age_days <= 3650:
            raise ValueError("'min_age_days' doit être compris entre 0 et 3650.")
        max_files = int(args.get("max_files", _MAX_FILES))
        if not 1 <= max_files <= _MAX_FILES:
            raise ValueError(f"'max_files' doit être compris entre 1 et {_MAX_FILES}.")
        delete = bool(args.get("delete", False))
        candidates = _normalized_candidates(candidate_provider)
        scan = await asyncio.to_thread(
            _scan,
            candidates,
            cutoff=time.time() - min_age_days * 86_400,
            delete=delete,
            max_files=max_files,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"error": str(exc)}

    locations = [
        {
            "dir": item["dir"],
            "size_human": format_bytes(item["total_size"]),
            "files": item["total_files"],
            "reclaimable_human": format_bytes(item["reclaimable_size"]),
            "reclaimable_files": item["reclaimable_files"],
            "errors": item["errors"],
            "truncated": item["truncated"],
        }
        for item in scan["report"]
    ]
    result = {
        "success": True,
        "locations": locations,
        "reclaimable_human": format_bytes(scan["reclaimable_size"]),
        "total_files": scan["total_files"],
        "reclaimable_files": scan["reclaimable_files"],
        "deleted": delete,
        "errors": scan["errors"],
        "truncated": scan["truncated"],
    }
    if delete:
        result.update(
            {
                "freed_human": format_bytes(scan["freed"]),
                "freed_files": scan["freed_files"],
                "message": (
                    f"Nettoyage : {format_bytes(scan['freed'])} libérés "
                    f"({scan['freed_files']} fichiers supprimés, > {min_age_days:g} j)."
                ),
            }
        )
    else:
        location_count = len(locations)
        location_label = "dossier temporaire inspecté" if location_count == 1 else "dossiers temporaires inspectés"
        result["message"] = (
            f"{format_bytes(scan['reclaimable_size'])} récupérables dans "
            f"{location_count} {location_label}."
        )
    return result
