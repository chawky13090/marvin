"""Inspection et transformations d'images locales de Marvin."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from platform_paths import PATHS as _SYSTEM_PATHS


_resolver: Callable[[str], str] | None = None
_MAX_PIXELS = 100_000_000
_MAX_BATCH_FILES = 5_000
_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}
_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}


def configure(*, resolve_path: Callable[[str], str]) -> None:
    global _resolver
    _resolver = resolve_path


def _resolve_path(raw: str) -> Path:
    if _resolver is None:
        raise RuntimeError("Le domaine Images n'est pas configuré")
    return Path(_resolver(raw))


def _positive_int(raw: object, name: str, *, maximum: int = 50_000) -> int:
    value = int(raw)
    if not 1 <= value <= maximum:
        raise ValueError(f"'{name}' doit être compris entre 1 et {maximum}.")
    return value


def _quality(raw: object, default: int = 85) -> int:
    return _positive_int(raw if raw is not None else default, "quality", maximum=100)


def _format(raw: object, fallback: str) -> str:
    value = str(raw or fallback).upper()
    if value == "JPG":
        value = "JPEG"
    if value not in _FORMATS:
        raise ValueError(
            f"Format non supporté : {value}. Utilisez JPEG, PNG, WEBP, BMP ou TIFF."
        )
    return value


def _open(path: Path) -> Image.Image:
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as source:
        width, height = source.size
        if width <= 0 or height <= 0 or width * height > _MAX_PIXELS:
            raise ValueError("Image refusée : dimensions invalides ou supérieures à 100 MP")
        source.load()
        result = ImageOps.exif_transpose(source).copy()
        result.format = source.format
        return result


def _temporary(destination: Path) -> Path:
    return destination.with_name(
        f".{destination.stem}.{os.getpid()}.{time.time_ns()}{destination.suffix}"
    )


def _save_atomic(
    image: Image.Image,
    destination: Path,
    *,
    image_format: str | None = None,
    **kwargs,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary(destination)
    try:
        image.save(temporary, format=image_format, **kwargs)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _rgb_for(image: Image.Image, image_format: str) -> Image.Image:
    if image_format == "JPEG" and image.mode in {"RGBA", "P", "LA"}:
        return image.convert("RGB")
    return image


async def info(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        path = _resolve_path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        with Image.open(path) as image:
            width, height = image.size
            if width * height > _MAX_PIXELS:
                raise ValueError("Image refusée : dimensions supérieures à 100 MP")
            exif_data: dict[str, str] = {}
            try:
                from PIL.ExifTags import TAGS

                for tag_id, value in image.getexif().items():
                    if isinstance(value, (str, int, float)):
                        exif_data[str(TAGS.get(tag_id, tag_id))] = str(value)
            except (AttributeError, TypeError, ValueError):
                pass
            size = path.stat().st_size
            return {
                "success": True,
                "path": str(path),
                "format": image.format or "inconnu",
                "mode": image.mode,
                "width": width,
                "height": height,
                "megapixels": round(width * height / 1_000_000, 2),
                "size_bytes": size,
                "size_kb": round(size / 1024, 1),
                "exif": exif_data,
            }
    except FileNotFoundError:
        return {"error": f"Fichier introuvable : {raw_path}"}
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        return {"error": str(exc)}


async def resize(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    if args.get("width") is None and args.get("height") is None:
        return {"error": "Spécifiez au moins 'width' ou 'height'."}
    try:
        source = _resolve_path(raw_path)
        image = _open(source)
        original_width, original_height = image.size
        width = (
            _positive_int(args["width"], "width")
            if args.get("width") is not None
            else None
        )
        height = (
            _positive_int(args["height"], "height")
            if args.get("height") is not None
            else None
        )
        if bool(args.get("keep_ratio", True)):
            if width and height:
                ratio = min(width / original_width, height / original_height)
                new_width = max(1, round(original_width * ratio))
                new_height = max(1, round(original_height * ratio))
            elif width:
                new_width = width
                new_height = max(1, round(original_height * width / original_width))
            else:
                new_height = height or original_height
                new_width = max(1, round(original_width * new_height / original_height))
        else:
            new_width, new_height = width or original_width, height or original_height
        if new_width * new_height > _MAX_PIXELS:
            raise ValueError("Image de sortie refusée : dimensions supérieures à 100 MP")

        output_format = _format(args.get("format"), image.format or "PNG")
        output_raw = str(args.get("output_path") or "").strip()
        extension = "jpg" if output_format == "JPEG" else output_format.lower()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_resized.{extension}")
        )
        resized = image.resize(
            (new_width, new_height), Image.Resampling.LANCZOS
        )
        kwargs = (
            {"quality": _quality(args.get("quality"), 85)}
            if output_format in {"JPEG", "WEBP"}
            else {}
        )
        _save_atomic(
            _rgb_for(resized, output_format),
            destination,
            image_format=output_format,
            **kwargs,
        )
        return {
            "success": True,
            "output": str(destination),
            "original": {"width": original_width, "height": original_height},
            "resized": {"width": new_width, "height": new_height},
            "format": output_format,
            "size_kb": round(destination.stat().st_size / 1024, 1),
        }
    except FileNotFoundError:
        return {"error": f"Fichier introuvable : {raw_path}"}
    except (OSError, TypeError, ValueError, UnidentifiedImageError) as exc:
        return {"error": str(exc)}


async def images_to_pdf(args: dict) -> dict:
    sources = args.get("sources") or args.get("images") or []
    if isinstance(sources, str):
        sources = [
            item.strip()
            for item in sources.replace("\n", ",").split(",")
            if item.strip()
        ]
    if not isinstance(sources, list) or not sources:
        return {"error": "Fournir des images dans 'sources'."}
    if len(sources) > _MAX_BATCH_FILES:
        return {"error": f"Trop d'images : maximum {_MAX_BATCH_FILES}."}
    images: list[Image.Image] = []
    try:
        for source in sources:
            images.append(_open(_resolve_path(str(source))).convert("RGB"))
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else Path(_SYSTEM_PATHS["desktop"]) / "images.pdf"
        )
        if destination.suffix.lower() != ".pdf":
            return {"error": "Le fichier de sortie doit utiliser l'extension .pdf."}
        dpi = float(args.get("dpi", 150))
        if not 36 <= dpi <= 1_200:
            return {"error": "'dpi' doit être compris entre 36 et 1200."}
        temporary = _temporary(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            images[0].save(
                temporary,
                "PDF",
                save_all=True,
                append_images=images[1:],
                resolution=dpi,
            )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "pages": len(images),
            "message": f"{len(images)} image(s) → PDF : {destination}",
        }
    except FileNotFoundError as exc:
        return {"error": f"Image introuvable : {exc.args[0]}"}
    except (OSError, TypeError, ValueError, UnidentifiedImageError) as exc:
        return {"error": str(exc)}
    finally:
        for image in images:
            image.close()


async def crop(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        source = _resolve_path(raw_path)
        image = _open(source)
        width, height = image.size
        if args.get("aspect"):
            values = str(args["aspect"]).replace("/", ":").split(":")
            if len(values) != 2:
                raise ValueError("aspect invalide (ex: '1:1', '16:9').")
            aspect_width, aspect_height = (float(value) for value in values)
            if aspect_width <= 0 or aspect_height <= 0:
                raise ValueError("aspect invalide (valeurs strictement positives requises).")
            target = aspect_width / aspect_height
            current = width / height
            if current > target:
                new_width = int(height * target)
                left = (width - new_width) // 2
                box = (left, 0, left + new_width, height)
            else:
                new_height = int(width / target)
                top = (height - new_height) // 2
                box = (0, top, width, top + new_height)
        else:
            box = (
                int(args.get("left", 0)),
                int(args.get("top", 0)),
                int(args.get("right", width)),
                int(args.get("bottom", height)),
            )
        if not (
            0 <= box[0] < box[2] <= width
            and 0 <= box[1] < box[3] <= height
        ):
            return {"error": "Boîte de rognage invalide ou hors de l'image."}
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_crop{source.suffix}")
        )
        cropped = image.crop(box)
        _save_atomic(cropped, destination, image_format=image.format)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "box": list(box),
            "size": [box[2] - box[0], box[3] - box[1]],
            "message": f"Image rognée → {destination}",
        }
    except FileNotFoundError:
        return {"error": f"Image introuvable : {raw_path}"}
    except (OSError, TypeError, ValueError, UnidentifiedImageError) as exc:
        return {"error": str(exc)}


async def rotate(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        source = _resolve_path(raw_path)
        image = _open(source)
        flip = str(args.get("flip") or "").lower()
        if flip in {"horizontal", "h"}:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        elif flip in {"vertical", "v"}:
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        elif flip:
            return {"error": "flip invalide. Utilisez horizontal ou vertical."}
        angle = float(args.get("angle", 0))
        if angle:
            image = image.rotate(-angle, expand=True)
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_rot{source.suffix}")
        )
        _save_atomic(image, destination, image_format=image.format)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "message": f"Image transformée → {destination}",
        }
    except FileNotFoundError:
        return {"error": f"Image introuvable : {raw_path}"}
    except (OSError, TypeError, ValueError, UnidentifiedImageError) as exc:
        return {"error": str(exc)}


async def compress(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        source = _resolve_path(raw_path)
        image = _open(source)
        output_format = _format(args.get("format"), "JPEG")
        if output_format not in {"JPEG", "WEBP"}:
            return {"error": "La compression prend en charge JPEG ou WEBP."}
        image = _rgb_for(image, output_format)
        extension = ".webp" if output_format == "WEBP" else ".jpg"
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_compresse{extension}")
        )
        original_size = source.stat().st_size
        target_kb = args.get("target_kb")
        qualities = (
            range(90, 19, -10)
            if target_kb
            else [_quality(args.get("quality"), 80)]
        )
        target = (
            _positive_int(target_kb, "target_kb", maximum=10_000_000) * 1024
            if target_kb
            else None
        )
        for quality in qualities:
            _save_atomic(
                image,
                destination,
                image_format=output_format,
                quality=quality,
                optimize=True,
            )
            if target is None or destination.stat().st_size <= target:
                break
        new_size = destination.stat().st_size
        saved = round((1 - new_size / original_size) * 100, 1) if original_size else 0
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "original_kb": round(original_size / 1024, 1),
            "compressed_kb": round(new_size / 1024, 1),
            "saved_pct": saved,
            "message": (
                f"{round(original_size / 1024, 1)} Ko → "
                f"{round(new_size / 1024, 1)} Ko ({round(saved)}% gagné)"
            ),
        }
    except FileNotFoundError:
        return {"error": f"Image introuvable : {raw_path}"}
    except (OSError, TypeError, ValueError, UnidentifiedImageError) as exc:
        return {"error": str(exc)}


async def batch(args: dict) -> dict:
    raw_directory = str(args.get("directory") or args.get("path") or "").strip()
    if not raw_directory:
        return {"error": "Paramètre 'directory' requis."}
    operation = str(args.get("operation") or "convert").lower()
    if operation not in {"convert", "resize", "compress", "rotate", "watermark"}:
        return {"error": "Opération invalide : convert, resize, compress, rotate ou watermark."}
    try:
        source_dir = _resolve_path(raw_directory)
        if not source_dir.is_dir():
            return {"error": f"Dossier introuvable : {source_dir}"}
        output_raw = str(args.get("output_dir") or "").strip()
        output_dir = (
            _resolve_path(output_raw)
            if output_raw
            else source_dir.parent / f"{source_dir.name}_traite"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        iterator = source_dir.rglob("*") if bool(args.get("recursive")) else source_dir.iterdir()
        files = sorted(
            path
            for path in iterator
            if path.is_file() and path.suffix.lower() in _EXTENSIONS
        )
        if not files:
            return {"error": f"Aucune image dans {source_dir}"}
        if len(files) > _MAX_BATCH_FILES:
            return {"error": f"Trop d'images : maximum {_MAX_BATCH_FILES}."}

        output_format_raw = args.get("format")
        width = args.get("width")
        height = args.get("height")
        quality = _quality(args.get("quality"), 85)
        target_kb = (
            _positive_int(args["target_kb"], "target_kb", maximum=10_000_000)
            if args.get("target_kb")
            else None
        )
        angle = float(args.get("angle", 0))
        flip = str(args.get("flip") or "").lower()
        watermark_text = str(args.get("text") or "")
        done: list[str] = []
        errors = 0
        for source in files:
            try:
                image = _open(source)
                extension = source.suffix
                save_format = image.format or "PNG"
                if operation == "convert":
                    save_format = _format(output_format_raw, save_format)
                    extension = "." + ("jpg" if save_format == "JPEG" else save_format.lower())
                elif operation == "resize":
                    target_width = int(width) if width else None
                    target_height = int(height) if height else None
                    if not target_width and not target_height:
                        raise ValueError("width ou height requis pour resize")
                    if target_width and target_height:
                        size = (target_width, target_height)
                    elif target_width:
                        size = (target_width, max(1, int(image.height * target_width / image.width)))
                    else:
                        size = (max(1, int(image.width * target_height / image.height)), target_height)
                    image = image.resize(size, Image.Resampling.LANCZOS)
                elif operation == "compress":
                    save_format, extension = "JPEG", ".jpg"
                elif operation == "rotate":
                    if flip in {"horizontal", "h"}:
                        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    elif flip in {"vertical", "v"}:
                        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                    elif flip:
                        raise ValueError("flip invalide")
                    if angle:
                        image = image.rotate(-angle, expand=True)
                elif operation == "watermark":
                    if not watermark_text:
                        raise ValueError("text requis pour watermark")
                    image = image.convert("RGBA")
                    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(overlay)
                    font_size = max(16, image.width // 18)
                    try:
                        font = ImageFont.truetype("arial.ttf", font_size)
                    except OSError:
                        font = ImageFont.load_default()
                    box = draw.textbbox((0, 0), watermark_text, font=font)
                    text_width, text_height = box[2] - box[0], box[3] - box[1]
                    draw.text(
                        (image.width - text_width - 12, image.height - text_height - 12),
                        watermark_text,
                        fill=(255, 255, 255, 160),
                        font=font,
                    )
                    image = Image.alpha_composite(image, overlay).convert("RGB")
                    save_format = "PNG" if source.suffix.lower() == ".png" else "JPEG"
                    extension = ".png" if save_format == "PNG" else ".jpg"
                destination = output_dir / f"{source.stem}{extension}"
                if operation == "compress" and target_kb:
                    for current_quality in range(90, 19, -10):
                        _save_atomic(
                            _rgb_for(image, save_format),
                            destination,
                            image_format=save_format,
                            quality=current_quality,
                            optimize=True,
                        )
                        if destination.stat().st_size <= target_kb * 1024:
                            break
                else:
                    kwargs = (
                        {"quality": quality, "optimize": True}
                        if save_format in {"JPEG", "WEBP"}
                        else {}
                    )
                    _save_atomic(
                        _rgb_for(image, save_format),
                        destination,
                        image_format=save_format,
                        **kwargs,
                    )
                done.append(str(destination))
            except (OSError, TypeError, ValueError, UnidentifiedImageError):
                errors += 1
        return {
            "success": True,
            "operation": operation,
            "processed": len(done),
            "errors": errors,
            "output_dir": str(output_dir),
            "files": done[:30],
            "message": (
                f"{len(done)} image(s) traitée(s) ({operation}) → {output_dir}"
                + (f" | {errors} échec(s)" if errors else "")
            ),
        }
    except (OSError, TypeError, ValueError) as exc:
        return {"error": str(exc)}
