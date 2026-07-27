"""Création et extraction bornée des archives manipulées par Marvin."""

from __future__ import annotations

import os
import shutil
import stat
import tarfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from platform_paths import PATHS as _SYSTEM_PATHS


_resolver: Callable[[str], str] | None = None
_MAX_MEMBERS = 20_000
_MAX_EXPANDED_BYTES = 8 * 1024 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 2_000


def configure(*, resolve_path: Callable[[str], str]) -> None:
    global _resolver
    _resolver = resolve_path


def _resolve_path(raw: str) -> str:
    if _resolver is None:
        raise RuntimeError("Le domaine archives n'est pas configuré")
    return _resolver(raw)


def _safe_target(destination: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if (
        not normalized
        or member.is_absolute()
        or member.drive
        or any(part in ("", ".", "..") for part in member.parts)
    ):
        raise ValueError(f"Chemin interne non sûr : {member_name!r}")
    target = destination.joinpath(*member.parts).resolve()
    try:
        target.relative_to(destination.resolve())
    except ValueError as exc:
        raise ValueError(f"Chemin interne hors destination : {member_name!r}") from exc
    return target


def _check_limits(count: int, expanded: int, compressed: int) -> None:
    if count > _MAX_MEMBERS:
        raise ValueError(f"Archive refusée : plus de {_MAX_MEMBERS} entrées")
    if expanded > _MAX_EXPANDED_BYTES:
        raise ValueError("Archive refusée : taille décompressée supérieure à 8 Gio")
    if compressed > 0 and expanded / compressed > _MAX_COMPRESSION_RATIO:
        raise ValueError("Archive refusée : taux de compression anormal")


def _rollback_created(created: list[Path], destination: Path, destination_created: bool) -> None:
    for path in reversed(created):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass
    if destination_created:
        try:
            destination.rmdir()
        except OSError:
            pass


def _extract_zip(archive: Path, destination: Path) -> list[str]:
    created: list[Path] = []
    destination_created = not destination.exists()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive, "r") as handle:
            members = handle.infolist()
            expanded = sum(item.file_size for item in members)
            compressed = sum(item.compress_size for item in members)
            _check_limits(len(members), expanded, compressed)
            names: list[str] = []
            for item in members:
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"Lien symbolique ZIP refusé : {item.filename!r}")
                target = _safe_target(destination, item.filename)
                names.append(item.filename)
                if item.is_dir():
                    if not target.exists():
                        target.mkdir(parents=True)
                        created.append(target)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                existed = target.exists()
                with handle.open(item, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                if not existed:
                    created.append(target)
            return names
    except Exception:
        _rollback_created(created, destination, destination_created)
        raise


def _extract_tar(archive: Path, destination: Path) -> list[str]:
    created: list[Path] = []
    destination_created = not destination.exists()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:*") as handle:
            members = handle.getmembers()
            expanded = sum(member.size for member in members if member.isfile())
            _check_limits(len(members), expanded, archive.stat().st_size)
            names: list[str] = []
            for member in members:
                if member.issym() or member.islnk():
                    raise ValueError(f"Lien TAR refusé : {member.name!r}")
                if not (member.isfile() or member.isdir()):
                    raise ValueError(f"Type d'entrée TAR refusé : {member.name!r}")
                target = _safe_target(destination, member.name)
                names.append(member.name)
                if member.isdir():
                    if not target.exists():
                        target.mkdir(parents=True)
                        created.append(target)
                    continue
                source = handle.extractfile(member)
                if source is None:
                    raise ValueError(f"Contenu TAR illisible : {member.name!r}")
                target.parent.mkdir(parents=True, exist_ok=True)
                existed = target.exists()
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                if not existed:
                    created.append(target)
            return names
    except Exception:
        _rollback_created(created, destination, destination_created)
        raise


async def compress(args: dict) -> dict:
    """Compresse des fichiers ou dossiers en ZIP."""
    sources = args.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]
    output_path = str(args.get("output_path") or "").strip()
    if not isinstance(sources, list) or not sources:
        return {"error": "Paramètre 'sources' requis (liste de fichiers/dossiers à compresser)."}

    try:
        resolved_sources = [Path(_resolve_path(str(source))) for source in sources]
    except (TypeError, ValueError, RuntimeError) as exc:
        return {"error": str(exc)}
    for source in resolved_sources:
        if not source.exists():
            return {"error": f"Fichier/dossier introuvable : {source}"}

    if output_path:
        out = Path(_resolve_path(output_path))
    else:
        out = Path(_SYSTEM_PATHS["desktop"]) / (
            f"{resolved_sources[0].stem}_{int(time.time())}.zip"
        )
    if not out.suffix:
        out = out.with_suffix(".zip")
    if out.suffix.lower() != ".zip":
        return {"error": "Le format de sortie pris en charge est .zip."}
    out.parent.mkdir(parents=True, exist_ok=True)

    temporary = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for source in resolved_sources:
                if source.is_dir():
                    for file in source.rglob("*"):
                        if (
                            file.is_file()
                            and file.resolve() not in {out.resolve(), temporary.resolve()}
                        ):
                            handle.write(file, arcname=str(file.relative_to(source.parent)))
                else:
                    handle.write(source, arcname=source.name)
        os.replace(temporary, out)
        size = out.stat().st_size
        return {
            "success": True,
            "message": f"Archive créée : {out}",
            "path": str(out),
            "size": (
                f"{size / 1024:.1f} KB"
                if size < 1024 * 1024
                else f"{size / 1024 / 1024:.1f} MB"
            ),
        }
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        return {"error": str(exc)}


async def list_contents(args: dict) -> dict:
    """Liste une archive ZIP après contrôle de structure et d'intégrité."""
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    archive = Path(_resolve_path(raw_path))
    if not archive.is_file():
        return {"error": f"Archive introuvable : {archive}"}
    try:
        with zipfile.ZipFile(archive, "r") as handle:
            members = handle.infolist()
            expanded = sum(item.file_size for item in members)
            compressed = sum(item.compress_size for item in members)
            _check_limits(len(members), expanded, compressed)
            corrupt = handle.testzip()
            if corrupt is not None:
                raise ValueError(f"Archive ZIP corrompue au membre : {corrupt}")
            entries = [
                {
                    "name": item.filename,
                    "size": item.file_size,
                    "compressed": item.compress_size,
                    "is_dir": item.is_dir(),
                    "date": (
                        f"{item.date_time[0]}-{item.date_time[1]:02d}-"
                        f"{item.date_time[2]:02d}"
                    ),
                }
                for item in members[:200]
            ]
        ratio = (
            f"{round((1 - compressed / expanded) * 100, 1)}%"
            if expanded > 0
            else "0%"
        )
        return {
            "success": True,
            "archive": str(archive),
            "entries_count": len(members),
            "total_size_kb": round(expanded / 1024, 1),
            "compressed_size_kb": round(compressed / 1024, 1),
            "compression_ratio": ratio,
            "entries": entries,
            "entries_truncated": len(members) > len(entries),
        }
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        return {"error": str(exc)}


async def extract(args: dict) -> dict:
    """Extrait une archive ZIP ou TAR sans autoriser de sortie du dossier cible."""
    raw_archive = str(args.get("archive_path") or "").strip()
    destination_raw = str(args.get("dest_path") or "").strip()
    if not raw_archive:
        return {"error": "Paramètre 'archive_path' requis."}

    archive = Path(_resolve_path(raw_archive))
    if not archive.is_file():
        return {"error": f"Archive introuvable : {archive}"}
    destination = (
        Path(_resolve_path(destination_raw))
        if destination_raw
        else archive.parent / archive.name.removesuffix(".tar.gz").removesuffix(".tar.bz2")
        .removesuffix(".tar.xz").removesuffix(archive.suffix)
    )

    try:
        lower_name = archive.name.lower()
        if lower_name.endswith(".zip"):
            names = _extract_zip(archive, destination)
        elif lower_name.endswith((".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")):
            names = _extract_tar(archive, destination)
        else:
            return {
                "error": (
                    f"Format d'archive non supporté : {archive.suffix.lower()}. "
                    "Utilisez .zip, .tar, .tar.gz, .tar.bz2, .tar.xz ou .tgz."
                )
            }
        return {
            "success": True,
            "message": f"Archive extraite dans : {destination}",
            "dest_path": str(destination),
            "files_extracted": len(names),
        }
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return {"error": str(exc)}
