"""Lecture et transformations structurelles PDF fondées sur pypdf."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterable

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from platform_paths import PATHS as _SYSTEM_PATHS


_resolver: Callable[[str], str] | None = None
_PAGE_CAP = 100_000
_SOURCE_CAP = 1_000
_MAX_TEXT_CHARS = 2_000_000


def configure(*, resolve_path: Callable[[str], str]) -> None:
    global _resolver
    _resolver = resolve_path


def _resolve_path(raw: str) -> Path:
    if _resolver is None:
        raise RuntimeError("Le domaine PDF n'est pas configuré")
    return Path(_resolver(raw))


def parse_pages(spec: object, total: int) -> list[int]:
    """Convertit une sélection 1-based en indices uniques 0-based et bornés."""
    try:
        bounded_total = min(max(0, int(total)), _PAGE_CAP)
    except (TypeError, ValueError):
        bounded_total = 0
    if spec is None or spec == "":
        return list(range(bounded_total))
    if isinstance(spec, (list, tuple, set)):
        parts: Iterable[object] = spec
    else:
        parts = str(spec).replace(" ", "").split(",")

    output: list[int] = []
    seen: set[int] = set()
    for raw_part in parts:
        part = str(raw_part).strip()
        if not part:
            continue
        try:
            if "-" in part:
                start_raw, _, end_raw = part.partition("-")
                start = max(1, int(start_raw)) if start_raw else 1
                end = min(int(end_raw), bounded_total) if end_raw else bounded_total
                candidates = range(start, end + 1)
            else:
                candidates = (int(part),)
            for page in candidates:
                index = page - 1
                if 0 <= index < bounded_total and index not in seen:
                    seen.add(index)
                    output.append(index)
        except ValueError:
            continue
    return output


def _reader(path: Path) -> PdfReader:
    if not path.is_file():
        raise FileNotFoundError(path)
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("PDF chiffré : déverrouillez-le avant cette opération.")
    if len(reader.pages) > _PAGE_CAP:
        raise ValueError(f"PDF refusé : plus de {_PAGE_CAP} pages.")
    return reader


def _temporary(destination: Path) -> Path:
    return destination.with_name(
        f".{destination.stem}.{os.getpid()}.{time.time_ns()}{destination.suffix}"
    )


def _write_atomic(writer: PdfWriter, destination: Path) -> None:
    if destination.suffix.lower() != ".pdf":
        raise ValueError("Le fichier de sortie doit utiliser l'extension .pdf.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary(destination)
    try:
        with temporary.open("wb") as handle:
            writer.write(handle)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


async def read(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        max_chars = int(args.get("max_chars", 4000))
        if not 1 <= max_chars <= _MAX_TEXT_CHARS:
            return {
                "error": (
                    f"'max_chars' doit être compris entre 1 et {_MAX_TEXT_CHARS}."
                )
            }
        path = _resolve_path(raw_path)
        reader = _reader(path)
        total = len(reader.pages)
        indices = parse_pages(args.get("pages"), total)
        texts = [
            {
                "page": index + 1,
                "text": (reader.pages[index].extract_text() or "").strip(),
            }
            for index in indices
        ]
        full_text = "\n\n".join(
            f"[Page {item['page']}]\n{item['text']}" for item in texts
        )
        return {
            "success": True,
            "file": str(path),
            "total_pages": total,
            "pages_read": len(texts),
            "text": full_text[:max_chars],
            "truncated": len(full_text) > max_chars,
            "chars": len(full_text),
        }
    except FileNotFoundError:
        return {"error": f"Fichier introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def info(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        path = _resolve_path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        reader = PdfReader(str(path))
        encrypted = reader.is_encrypted
        metadata = {} if encrypted else (reader.metadata or {})
        page_count = 0 if encrypted else len(reader.pages)
        stat = path.stat()
        return {
            "success": True,
            "file": str(path),
            "pages": page_count,
            "size_kb": round(stat.st_size / 1024, 1),
            "encrypted": encrypted,
            "page_count_unavailable": encrypted,
            "title": metadata.get("/Title", "") or "",
            "author": metadata.get("/Author", "") or "",
            "subject": metadata.get("/Subject", "") or "",
            "creator": metadata.get("/Creator", "") or "",
            "producer": metadata.get("/Producer", "") or "",
            "created": str(metadata.get("/CreationDate", "") or ""),
            "modified": str(metadata.get("/ModDate", "") or ""),
        }
    except FileNotFoundError:
        return {"error": f"Fichier introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def merge(args: dict) -> dict:
    sources = args.get("sources") or args.get("paths") or []
    if isinstance(sources, str):
        sources = [
            item.strip()
            for item in sources.replace("\n", ",").split(",")
            if item.strip()
        ]
    if not isinstance(sources, list) or len(sources) < 2:
        return {"error": "Fournir au moins 2 PDF dans 'sources'."}
    if len(sources) > _SOURCE_CAP:
        return {"error": f"Trop de PDF : maximum {_SOURCE_CAP}."}
    try:
        destination_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(destination_raw)
            if destination_raw
            else Path(_SYSTEM_PATHS["desktop"]) / "fusion.pdf"
        )
        writer = PdfWriter()
        total = 0
        for source in sources:
            source_path = _resolve_path(str(source))
            reader = _reader(source_path)
            total += len(reader.pages)
            if total > _PAGE_CAP:
                return {"error": f"Fusion refusée : plus de {_PAGE_CAP} pages."}
            for page in reader.pages:
                writer.add_page(page)
        _write_atomic(writer, destination)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "pages": total,
            "merged": len(sources),
            "message": (
                f"{len(sources)} PDF fusionnés ({total} pages) → {destination}"
            ),
        }
    except FileNotFoundError as exc:
        return {"error": f"PDF introuvable : {exc.args[0]}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def split(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        source = _resolve_path(raw_path)
        reader = _reader(source)
        total = len(reader.pages)
        indices = parse_pages(args.get("pages"), total)
        if not indices:
            return {"error": "La sélection ne contient aucune page valide."}
        output_raw = str(args.get("output_dir") or "").strip()
        output_dir = _resolve_path(output_raw) if output_raw else source.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        per_page = bool(args.get("per_page", not args.get("pages")))
        created: list[str] = []
        if per_page:
            for index in indices:
                writer = PdfWriter()
                writer.add_page(reader.pages[index])
                destination = output_dir / f"{source.stem}_p{index + 1}.pdf"
                _write_atomic(writer, destination)
                created.append(str(destination))
        else:
            writer = PdfWriter()
            for index in indices:
                writer.add_page(reader.pages[index])
            destination = output_dir / f"{source.stem}_extrait.pdf"
            _write_atomic(writer, destination)
            created.append(str(destination))
        return {
            "success": True,
            "files": created,
            "count": len(created),
            "path": created[0],
            "destination": created[0],
            "message": f"{len(created)} fichier(s) créé(s) depuis {total} pages",
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def rotate(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        angle = int(args.get("angle", 90))
        if angle % 90 != 0:
            return {"error": "L'angle doit être un multiple de 90 (90, 180, 270)."}
        source = _resolve_path(raw_path)
        reader = _reader(source)
        targets = set(parse_pages(args.get("pages"), len(reader.pages)))
        if not targets:
            return {"error": "La sélection ne contient aucune page valide."}
        writer = PdfWriter()
        for index, page in enumerate(reader.pages):
            if index in targets:
                page.rotate(angle)
            writer.add_page(page)
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_pivote.pdf")
        )
        _write_atomic(writer, destination)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "rotated_pages": len(targets),
            "message": (
                f"{len(targets)} page(s) pivotée(s) de {angle}° → {destination}"
            ),
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}
