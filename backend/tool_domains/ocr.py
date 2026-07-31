"""OCR vision avec routage de confidentialité et entrées bornées."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Awaitable, Callable

import httpx

import cloud_routing


_resolver: Callable[[str], str] | None = None
_ollama_url = ""
_requester: Callable[..., Awaitable[dict]] | None = None
_MAX_INPUT_BYTES = 25 * 1024 * 1024
_MAX_IMAGE_PIXELS = 100_000_000
_MAX_DIMENSION = 1920


def configure(
    *,
    resolve_path: Callable[[str], str],
    ollama_url: str,
    requester: Callable[..., Awaitable[dict]] | None = None,
) -> None:
    global _resolver, _ollama_url, _requester
    _resolver = resolve_path
    _ollama_url = ollama_url.rstrip("/")
    _requester = requester


def _resolve_path(raw: str) -> str:
    if _resolver is None:
        raise RuntimeError("Le domaine OCR n'est pas configuré")
    return _resolver(raw)


async def _request_json(
    method: str,
    path: str,
    *,
    timeout: float,
    payload: dict | None = None,
) -> dict:
    if _requester is not None:
        return await _requester(method, path, timeout=timeout, payload=payload)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            method, f"{_ollama_url}{path}", json=payload
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Réponse Ollama invalide : objet JSON attendu")
        return data


def encode_image(path: Path) -> tuple[str, bool]:
    size = path.stat().st_size
    if size > _MAX_INPUT_BYTES:
        raise ValueError("Image refusée : taille supérieure à 25 Mio")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return base64.b64encode(path.read_bytes()).decode("ascii"), False

    try:
        with Image.open(path) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > _MAX_IMAGE_PIXELS:
                raise ValueError("Image refusée : dimensions invalides ou supérieures à 100 MP")
            source.load()
            image = source.copy()
            original_format = source.format
    except UnidentifiedImageError as exc:
        raise ValueError("Le fichier fourni n'est pas une image reconnue") from exc

    original_size = image.size
    if max(image.size) > _MAX_DIMENSION:
        ratio = _MAX_DIMENSION / max(image.size)
        image = image.resize(
            (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    output = io.BytesIO()
    output_format = original_format if original_format in {"PNG", "JPEG", "WEBP"} else "PNG"
    image.save(output, format=output_format)
    return base64.b64encode(output.getvalue()).decode("ascii"), image.size != original_size


async def extract(args: dict) -> dict:
    """Extrait le texte d'une image avec routage local/cloud conforme au mode actif."""
    image_raw = str(args.get("image_path") or "").strip()
    prompt = str(
        args.get("prompt")
        or "Extrais tout le texte présent dans cette image. "
        "Retourne uniquement le texte brut, sans commentaire."
    ).strip()
    requested_model = str(args.get("model") or "llava-phi3").strip()
    if not image_raw:
        return {"error": "Paramètre 'image_path' requis."}
    if not prompt:
        return {"error": "Le prompt OCR ne peut pas être vide."}

    try:
        model = cloud_routing.resolve_model(
            requested_model,
            profile="vision",
            local_fallback="llava-phi3",
            text_for_sensitivity=prompt,
            has_images=True,
        )
    except cloud_routing.CloudOnlyModelUnavailable as exc:
        return {"error": str(exc), "cloud_only": True}

    if not cloud_routing.is_cloud_model(model) and model != "llava-phi3":
        try:
            tags = await _request_json("GET", "/api/tags", timeout=5)
            installed = {
                str(item.get("name") or "")
                for item in tags.get("models", [])
                if isinstance(item, dict)
            }
            installed |= {
                name.removesuffix(":latest")
                for name in installed
                if name.endswith(":latest")
            }
            if model not in installed:
                model = "llava-phi3"
        except (httpx.HTTPError, OSError, TypeError, ValueError):
            pass

    resolved = Path(_resolve_path(image_raw))
    if not resolved.is_file():
        return {"error": f"Fichier introuvable : {resolved}"}
    try:
        image_b64, resized = encode_image(resolved)
    except (OSError, ValueError) as exc:
        return {"error": f"Erreur lecture image : {exc}"}

    async def _call(target_model: str) -> dict:
        data = await _request_json(
            "POST",
            "/api/generate",
            timeout=120,
            payload={
                "model": target_model,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
            },
        )
        extracted = str(data.get("response") or "").strip()
        return {
            "success": True,
            "image": str(resolved),
            "model": target_model,
            "text": extracted,
            "char_count": len(extracted),
            "resized_for_speed": resized,
        }

    try:
        return await _call(model)
    except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
        # Un modèle cloud indisponible (crédit épuisé, 402, hors-ligne...) ne doit pas
        # rendre l'OCR totalement inopérant s'il existe un modèle vision local : on
        # retente une fois avec le fallback local avant d'abandonner.
        if cloud_routing.is_cloud_model(model) and model != "llava-phi3":
            try:
                result = await _call("llava-phi3")
                result["fallback_from_cloud"] = model
                return result
            except (httpx.HTTPError, OSError, TypeError, ValueError):
                pass
        return {
            "error": (
                f"Erreur OCR : {exc}. "
                f"Vérifiez que le modèle {model} est disponible dans Ollama."
            )
        }
