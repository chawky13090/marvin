"""Capture d'écran OCR bornée avec provenance du moteur et nettoyage garanti."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


Capture = Callable[[dict[str, int] | None], tuple[Any, list[int]]]
VisionOcr = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
TesseractOcr = Callable[[Any, str], str]

_capture: Capture | None = None
_vision_ocr: VisionOcr | None = None
_tesseract_ocr: TesseractOcr | None = None
_is_cloud_model: Callable[[str], bool] | None = None
_output_dir = Path.cwd()
_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:12]
_DEFAULT_PROMPT = (
    "Extrais tout le texte visible dans cette image. "
    "Retourne uniquement le texte brut."
)
_MAX_PIXELS = 100_000_000
_MAX_DIMENSION = 16_384
_MAX_PROMPT_LENGTH = 4_000
_MAX_TEXT_LENGTH = 200_000
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{3}(?:\+[A-Za-z]{3}){0,4}$")


def _default_capture(region: dict[str, int] | None) -> tuple[Any, list[int]]:
    import mss
    from PIL import Image

    with mss.mss() as session:
        monitor = region if region is not None else session.monitors[0]
        shot = session.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return image, [int(shot.size.width), int(shot.size.height)]


def _default_tesseract(image: Any, language: str) -> str:
    import pytesseract

    try:
        return str(
            pytesseract.image_to_string(
                image, lang=language, config="--oem 3 --psm 6"
            )
        ).strip()
    except Exception:
        return str(
            pytesseract.image_to_string(
                image, config="--oem 3 --psm 6"
            )
        ).strip()


def configure(
    *,
    vision_ocr: VisionOcr,
    is_cloud_model: Callable[[str], bool],
    output_dir: str | os.PathLike[str],
    capture: Capture | None = None,
    tesseract_ocr: TesseractOcr | None = None,
    id_factory: Callable[[], str] | None = None,
) -> None:
    global _capture, _vision_ocr, _tesseract_ocr
    global _is_cloud_model, _output_dir, _id_factory
    _capture = capture or _default_capture
    _vision_ocr = vision_ocr
    _tesseract_ocr = tesseract_ocr or _default_tesseract
    _is_cloud_model = is_cloud_model
    _output_dir = Path(output_dir)
    _id_factory = id_factory or (lambda: uuid.uuid4().hex[:12])


def _dependencies() -> tuple[
    Capture,
    VisionOcr,
    TesseractOcr,
    Callable[[str], bool],
]:
    if (
        _capture is None
        or _vision_ocr is None
        or _tesseract_ocr is None
        or _is_cloud_model is None
    ):
        raise RuntimeError("Le domaine OCR écran n'est pas configuré.")
    return _capture, _vision_ocr, _tesseract_ocr, _is_cloud_model


def _validated_region(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise ValueError("'region' doit être [x, y, largeur, hauteur].")
    x, y, width, height = value
    if not -100_000 <= x <= 100_000 or not -100_000 <= y <= 100_000:
        raise ValueError("Les coordonnées de 'region' sont hors limites.")
    if not 1 <= width <= _MAX_DIMENSION or not 1 <= height <= _MAX_DIMENSION:
        raise ValueError(
            f"Largeur et hauteur de 'region' doivent être comprises entre 1 et {_MAX_DIMENSION}."
        )
    if width * height > _MAX_PIXELS:
        raise ValueError("La région OCR est limitée à 100 mégapixels.")
    return {"left": x, "top": y, "width": width, "height": height}


def _validated_args(
    args: dict[str, Any],
) -> tuple[dict[str, int] | None, bool, str, str, str]:
    region = _validated_region(args.get("region"))
    save = args.get("save", False)
    if not isinstance(save, bool):
        raise ValueError("'save' doit être un booléen.")
    method = args.get("method", "auto")
    if not isinstance(method, str) or method not in {"auto", "vision", "tesseract"}:
        raise ValueError("'method' doit valoir auto, vision ou tesseract.")
    prompt = args.get("prompt", _DEFAULT_PROMPT)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("'prompt' doit être une chaîne non vide.")
    prompt = prompt.strip()
    if len(prompt) > _MAX_PROMPT_LENGTH:
        raise ValueError(f"'prompt' est limité à {_MAX_PROMPT_LENGTH} caractères.")
    language = args.get("lang", "fra+eng")
    if not isinstance(language, str) or not _LANGUAGE_PATTERN.fullmatch(language):
        raise ValueError("'lang' doit contenir des codes Tesseract comme fra+eng.")
    return region, save, method, prompt, language


def _resize(image: Any) -> tuple[Any, bool]:
    from PIL import Image

    if max(image.size) <= 1_920:
        return image, False
    ratio = 1_920 / max(image.size)
    resized = image.resize(
        (
            max(1, int(image.width * ratio)),
            max(1, int(image.height * ratio)),
        ),
        Image.Resampling.LANCZOS,
    )
    return resized, True


def _save_atomic(image: Any, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        image.save(temporary, format="PNG")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


async def extract(args: dict[str, Any]) -> dict[str, Any]:
    """Capture l'écran puis applique la politique vision locale/Cloud existante."""
    try:
        region, save, method, prompt, language = _validated_args(args)
        capture, vision_ocr, tesseract_ocr, is_cloud_model = _dependencies()
        original, screen_size = await asyncio.to_thread(capture, region)
        if (
            not isinstance(screen_size, list)
            or len(screen_size) != 2
            or any(not isinstance(value, int) or value <= 0 for value in screen_size)
        ):
            raise ValueError("Dimensions de capture invalides.")
        if screen_size[0] * screen_size[1] > _MAX_PIXELS:
            raise ValueError("La capture dépasse 100 mégapixels.")
        image, resized = await asyncio.to_thread(_resize, original)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"error": f"Capture OCR impossible : {str(exc)[:200]}"}

    attempts: list[dict[str, Any]] = []
    text = ""
    method_used = "none"
    model = None
    cloud = False
    temporary_path: Path | None = None
    try:
        if method in {"auto", "vision"}:
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False
                ) as temporary:
                    temporary_path = Path(temporary.name)
                await asyncio.to_thread(
                    image.save, temporary_path, "PNG"
                )
                result = await vision_ocr(
                    {"image_path": str(temporary_path), "prompt": prompt}
                )
                if result.get("error"):
                    raise RuntimeError(str(result["error"]))
                candidate = str(result.get("text") or "").strip()
                if not candidate:
                    raise RuntimeError("réponse OCR vide")
                text = candidate
                model = str(result.get("model") or "") or None
                cloud = bool(model and is_cloud_model(model))
                method_used = "vision"
                attempts.append(
                    {
                        "method": "vision",
                        "status": "ok",
                        "model": model,
                        "cloud": cloud,
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempts.append(
                    {
                        "method": "vision",
                        "status": "error",
                        "error": str(exc)[:160],
                    }
                )

        if not text and method in {"auto", "tesseract"}:
            try:
                text = (
                    await asyncio.to_thread(
                        tesseract_ocr, image, language
                    )
                ).strip()
                if not text:
                    raise RuntimeError("réponse OCR vide")
                method_used = "tesseract"
                attempts.append({"method": "tesseract", "status": "ok"})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempts.append(
                    {
                        "method": "tesseract",
                        "status": "error",
                        "error": str(exc)[:160],
                    }
                )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    full_length = len(text)
    truncated = full_length > _MAX_TEXT_LENGTH
    result: dict[str, Any] = {
        "success": bool(text),
        "text": text[:_MAX_TEXT_LENGTH],
        "text_length": full_length,
        "truncated": truncated,
        "screen_size": screen_size,
        "processed_size": list(image.size),
        "resized_for_ocr": resized,
        "method": method_used,
        "model": model,
        "cloud": cloud,
        "attempts": attempts,
    }
    if save:
        destination = _output_dir / f"screen_ocr_{_id_factory()}.png"
        try:
            await asyncio.to_thread(_save_atomic, original, destination)
            result["saved_to"] = str(destination)
            result["rollback"] = {
                "available": True,
                "action": "delete_file",
                "path": str(destination),
            }
        except (OSError, ValueError) as exc:
            result["save_error"] = str(exc)[:200]
    if not text:
        result["error"] = (
            "Aucun texte extrait; consulte 'attempts' pour identifier "
            "le moteur absent, indisponible ou sans résultat."
        )
    return result
