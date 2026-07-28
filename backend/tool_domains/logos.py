"""Génération et catalogue de logos locaux avec dépendances injectées."""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


_availability: Callable[[], dict[str, Any]] | None = None
_generate_image: Callable[..., dict[str, Any]] | None = None
_create_record: Callable[[str, str, str], Any] | None = None
_list_records: Callable[..., list[dict[str, Any]]] | None = None
_output_root: Path | None = None
_token_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:8]
_generation_lock = asyncio.Lock()

_ALLOWED_SIZES = {256, 384, 512, 640, 768, 1024}


def configure(
    *,
    availability: Callable[[], dict[str, Any]],
    generate_image: Callable[..., dict[str, Any]],
    create_record: Callable[[str, str, str], Any],
    list_records: Callable[..., list[dict[str, Any]]],
    output_root: str | Path,
    token_factory: Callable[[], str] | None = None,
) -> None:
    global _availability, _generate_image, _create_record, _list_records
    global _output_root, _token_factory
    _availability = availability
    _generate_image = generate_image
    _create_record = create_record
    _list_records = list_records
    _output_root = Path(output_root).resolve()
    _token_factory = token_factory or (lambda: uuid.uuid4().hex[:8])


def _require_dependencies() -> None:
    if any(
        value is None
        for value in (
            _availability,
            _generate_image,
            _create_record,
            _list_records,
            _output_root,
        )
    ):
        raise RuntimeError("Le domaine Logos n'est pas configuré.")


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _error_text(value: Any) -> str:
    return re.sub(r"[\r\n\t]+", " ", str(value or "Échec de génération locale."))[:300]


async def generate(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    name = str(args.get("name") or "logo").strip()[:120] or "logo"
    prompt = str(args.get("prompt") or args.get("description") or "").strip()[:4000]
    if not prompt:
        return {"error": "Paramètre 'prompt' requis."}
    try:
        requested_size = int(args.get("size") or 512)
    except (TypeError, ValueError):
        return {"error": "La taille du logo doit être un entier."}
    if requested_size not in _ALLOWED_SIZES:
        return {
            "error": "Taille non prise en charge.",
            "allowed_sizes": sorted(_ALLOWED_SIZES),
        }
    seed_value = args.get("seed")
    seed: int | None = None
    if seed_value not in (None, ""):
        try:
            seed = int(seed_value)
        except (TypeError, ValueError):
            return {"error": "La graine doit être un entier."}
        if not 0 <= seed <= 2**32 - 1:
            return {"error": "La graine doit être comprise entre 0 et 4294967295."}

    assert _availability and _generate_image and _create_record and _output_root
    availability = await asyncio.to_thread(_availability)
    if not availability.get("ok"):
        return {"error": _error_text(availability.get("reason"))}

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "logo"
    token = re.sub(r"[^a-zA-Z0-9_-]", "", str(_token_factory()))[:24] or "generated"
    final_path = (_output_root / f"{slug}-{token}.png").resolve()
    if final_path.parent != _output_root:
        return {"error": "Chemin de sortie Logo invalide."}
    temporary = final_path.with_name(f".{final_path.stem}.tmp.png")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists() or temporary.exists():
        return {"error": "Collision de nom Logo; veuillez réessayer."}

    try:
        async with _generation_lock:
            result = await asyncio.to_thread(
                _generate_image,
                prompt,
                str(temporary),
                requested_size,
                seed,
            )
        if not result.get("success"):
            temporary.unlink(missing_ok=True)
            return {"error": _error_text(result.get("error"))}
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            temporary.unlink(missing_ok=True)
            return {"error": "Le générateur n'a produit aucun fichier image valide."}
        os.replace(temporary, final_path)
        try:
            await asyncio.to_thread(_create_record, name, prompt, str(final_path))
        except Exception:
            final_path.unlink(missing_ok=True)
            return {"error": "Le logo n'a pas pu être enregistré dans le catalogue."}
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        return {
            "error": "La génération locale du logo a échoué.",
            "error_type": type(exc).__name__[:80],
        }
    return {
        "success": True,
        "path": str(final_path),
        "name": name,
        "size": requested_size,
        "seed": seed,
        "generation_seconds": result.get("generation_seconds"),
        "device": str(result.get("device") or "")[:120],
        "bytes": final_path.stat().st_size,
        "message": f"Logo généré localement : {final_path}",
    }


async def list_logos(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    limit = _bounded_int(args.get("limit"), 50, 1, 200)
    assert _list_records is not None
    try:
        records = await asyncio.to_thread(_list_records, limit=limit)
    except Exception as exc:
        return {
            "error": "Le catalogue des logos est indisponible.",
            "error_type": type(exc).__name__[:80],
        }
    projected = []
    for record in records[:limit] if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        projected.append(
            {
                "id": record.get("id"),
                "name": str(record.get("name") or "")[:120],
                "prompt": str(record.get("prompt") or "")[:4000],
                "path": str(record.get("path") or "")[:1000],
                "created_at": record.get("created_at"),
            }
        )
    return {"success": True, "count": len(projected), "logos": projected}
