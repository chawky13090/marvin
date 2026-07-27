"""Traitements PDF avancés : rendu, OCR, formulaires, filigranes et compression."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import shutil
import time
from pathlib import Path
from typing import Awaitable, Callable

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from tool_domains.pdf_core import parse_pages


_resolver: Callable[[str], str] | None = None
_text_generator: Callable[..., Awaitable[str]] | None = None
_get_setting: Callable[[str], object] | None = None
_PAGE_CAP = 10_000
_EXTRACTED_IMAGE_CAP = 10_000


def configure(
    *,
    resolve_path: Callable[[str], str],
    text_generator: Callable[..., Awaitable[str]],
    get_setting: Callable[[str], object],
) -> None:
    global _resolver, _text_generator, _get_setting
    _resolver = resolve_path
    _text_generator = text_generator
    _get_setting = get_setting


def _resolve_path(raw: str) -> Path:
    if _resolver is None:
        raise RuntimeError("Le domaine PDF avancé n'est pas configuré")
    return Path(_resolver(raw))


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


def _write_pdf(writer: PdfWriter, destination: Path) -> None:
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


def _atomic_text(destination: Path, text: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary(destination)
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _page_stamp(width: float, height: float, draw: Callable) -> object:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, pagesize=(width, height))
    draw(document, width, height)
    document.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


async def watermark(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    text = str(args.get("text") or "").strip()
    if not raw_path or not text:
        return {"error": "Paramètres 'path' et 'text' requis."}
    try:
        opacity = float(args.get("opacity", 0.12))
        if not 0 <= opacity <= 1:
            return {"error": "'opacity' doit être compris entre 0 et 1."}
        source = _resolve_path(raw_path)
        reader = _reader(source)
        writer = PdfWriter()
        for page in reader.pages:
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            font_size = int(
                args.get("font_size", max(28, int(min(width, height) / 12)))
            )
            if not 6 <= font_size <= 500:
                return {"error": "'font_size' doit être compris entre 6 et 500."}

            def draw(canvas, page_width, page_height):
                from reportlab.lib.colors import Color

                canvas.saveState()
                canvas.translate(page_width / 2, page_height / 2)
                canvas.rotate(45)
                canvas.setFillColor(Color(0.5, 0.5, 0.5, alpha=opacity))
                canvas.setFont("Helvetica-Bold", font_size)
                canvas.drawCentredString(0, 0, text)
                canvas.restoreState()

            page.merge_page(_page_stamp(width, height, draw))
            writer.add_page(page)
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_filigrane.pdf")
        )
        _write_pdf(writer, destination)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "pages": len(reader.pages),
            "message": (
                f"Filigrane « {text} » apposé sur {len(reader.pages)} page(s) "
                f"→ {destination}"
            ),
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def protect(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    password = str(args.get("password") or "")
    if not raw_path or not password:
        return {"error": "Paramètres 'path' et 'password' requis."}
    if len(password) > 1_024:
        return {"error": "Mot de passe trop long (maximum 1 024 caractères)."}
    try:
        source = _resolve_path(raw_path)
        reader = _reader(source)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(
            user_password=password,
            owner_password=str(args.get("owner_password") or "") or None,
            algorithm="AES-256",
        )
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_protege.pdf")
        )
        _write_pdf(writer, destination)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "encrypted": True,
            "message": f"PDF protégé par mot de passe (AES-256) → {destination}",
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def extract_images(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        source = _resolve_path(raw_path)
        reader = _reader(source)
        output_raw = str(args.get("output_dir") or "").strip()
        output_dir = (
            _resolve_path(output_raw)
            if output_raw
            else source.parent / f"{source.stem}_images"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for page_index, page in enumerate(reader.pages):
            try:
                embedded = page.images
            except (AttributeError, PdfReadError):
                embedded = []
            for image_index, image in enumerate(embedded):
                if len(saved) >= _EXTRACTED_IMAGE_CAP:
                    raise ValueError(
                        f"Extraction interrompue : plus de {_EXTRACTED_IMAGE_CAP} images"
                    )
                try:
                    source_name = Path(str(image.name or "image.png"))
                    safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", source_name.stem)[:40]
                    extension = source_name.suffix.lower()
                    if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
                        extension = ".bin"
                    destination = output_dir / (
                        f"p{page_index + 1}_{image_index + 1}_{safe_stem}{extension}"
                    )
                    temporary = _temporary(destination)
                    try:
                        temporary.write_bytes(image.data)
                        os.replace(temporary, destination)
                    finally:
                        temporary.unlink(missing_ok=True)
                    saved.append(str(destination))
                except (OSError, TypeError, ValueError):
                    continue
        if not saved:
            return {
                "success": True,
                "count": 0,
                "files": [],
                "output_dir": str(output_dir),
                "message": "Aucune image intégrée trouvée dans ce PDF.",
            }
        return {
            "success": True,
            "count": len(saved),
            "files": saved[:50],
            "output_dir": str(output_dir),
            "path": saved[0],
            "message": f"{len(saved)} image(s) extraite(s) → {output_dir}",
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def to_images(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        import pypdfium2 as pdfium

        source = _resolve_path(raw_path)
        if not source.is_file():
            raise FileNotFoundError(source)
        dpi = float(args.get("dpi", 150))
        if not 36 <= dpi <= 600:
            return {"error": "'dpi' doit être compris entre 36 et 600."}
        output_raw = str(args.get("output_dir") or "").strip()
        output_dir = (
            _resolve_path(output_raw)
            if output_raw
            else source.parent / f"{source.stem}_pages"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        page_spec = args.get("pages")

        def render() -> tuple[list[str], int]:
            document = pdfium.PdfDocument(str(source))
            saved: list[str] = []
            try:
                total = len(document)
                indices = parse_pages(page_spec, total)
                for index in indices:
                    image = document[index].render(scale=dpi / 72.0).to_pil()
                    destination = output_dir / f"{source.stem}_p{index + 1}.png"
                    temporary = _temporary(destination)
                    try:
                        image.save(temporary, format="PNG")
                        os.replace(temporary, destination)
                    finally:
                        image.close()
                        temporary.unlink(missing_ok=True)
                    saved.append(str(destination))
                return saved, total
            finally:
                document.close()

        saved, total = await asyncio.to_thread(render)
        return {
            "success": True,
            "count": len(saved),
            "files": saved[:50],
            "output_dir": str(output_dir),
            "path": saved[0] if saved else "",
            "total_pages": total,
            "message": f"{len(saved)} page(s) rendue(s) en PNG → {output_dir}",
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (ImportError, OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


def _image_b64(image, image_format: str = "JPEG") -> str:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


async def ocr(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    if _text_generator is None or _get_setting is None:
        return {"error": "Le moteur OCR PDF n'est pas configuré."}
    try:
        import pypdfium2 as pdfium

        source = _resolve_path(raw_path)
        reader = _reader(source)
        total = len(reader.pages)
        try:
            max_pages = int(args.get("max_pages") or _get_setting("ocr_max_pages") or 15)
        except (TypeError, ValueError):
            max_pages = 15
        if not 1 <= max_pages <= 500:
            return {"error": "'max_pages' doit être compris entre 1 et 500."}
        try:
            scale = float(args.get("scale") or _get_setting("ocr_scale") or 2.0)
        except (TypeError, ValueError):
            scale = 2.0
        if not 0.5 <= scale <= 5:
            return {"error": "'scale' doit être compris entre 0.5 et 5."}
        targets = parse_pages(args.get("pages"), total)[:max_pages]
        if not targets:
            return {"error": "La sélection ne contient aucune page valide."}
        model = str(args.get("model") or "llava-phi3")
        document = await asyncio.to_thread(pdfium.PdfDocument, str(source))
        output_pages: list[str] = []
        ocr_count = 0
        try:
            for index in targets:
                try:
                    text = (reader.pages[index].extract_text() or "").strip()
                except (PdfReadError, TypeError, ValueError):
                    text = ""
                if len(text) < 25:
                    def render() -> str:
                        image = document[index].render(scale=scale).to_pil()
                        try:
                            cap = int(1920 * (scale / 2.0))
                            if max(image.size) > cap:
                                ratio = cap / max(image.size)
                                image = image.resize(
                                    (
                                        max(1, int(image.width * ratio)),
                                        max(1, int(image.height * ratio)),
                                    )
                                )
                            return _image_b64(image)
                        finally:
                            image.close()

                    encoded = await asyncio.to_thread(render)
                    text = await _text_generator(
                        "Extrais TOUT le texte de cette page. Retourne uniquement "
                        "le texte brut, sans commentaire.",
                        model=model,
                        images=[encoded],
                        timeout=180,
                    )
                    ocr_count += 1
                output_pages.append(f"--- Page {index + 1} ---\n{text.strip()}")
        finally:
            await asyncio.to_thread(document.close)
        full_text = "\n\n".join(output_pages)
        saved: str | None = None
        output_raw = str(args.get("output_path") or "").strip()
        if output_raw:
            destination = _resolve_path(output_raw)
            _atomic_text(destination, full_text)
            saved = str(destination)
        return {
            "success": True,
            "pages_processed": len(targets),
            "total_pages": total,
            "ocr_pages": ocr_count,
            "text": full_text[:8000],
            "truncated": len(full_text) > 8000,
            "path": saved,
            "message": (
                f"OCR terminé : {len(targets)} page(s), {ocr_count} via vision IA"
            ),
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (ImportError, OSError, PdfReadError, RuntimeError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def form_fields(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        reader = _reader(_resolve_path(raw_path))
        fields = reader.get_fields() or {}
        output = [
            {
                "name": name,
                "type": str(field.get("/FT", "")).lstrip("/") or "text",
                "value": str(field.get("/V", "") or ""),
                "options": [str(option) for option in (field.get("/Opt") or [])][:20],
            }
            for name, field in fields.items()
        ]
        return {
            "success": True,
            "count": len(output),
            "fields": output,
            "message": (
                f"{len(output)} champ(s) de formulaire"
                if output
                else "Aucun champ de formulaire (PDF non interactif)."
            ),
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def fill_form(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    data = args.get("data") or args.get("fields") or {}
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    if not isinstance(data, dict) or not data:
        return {"error": "Paramètre 'data' requis : un objet {nom_du_champ: valeur}."}
    if len(data) > 1_000:
        return {"error": "Trop de champs : maximum 1 000."}
    try:
        source = _resolve_path(raw_path)
        reader = _reader(source)
        known_fields = reader.get_fields() or {}
        unknown = sorted(set(map(str, data)) - set(known_fields))
        if unknown:
            return {"error": f"Champ(s) inconnu(s) : {', '.join(unknown[:20])}"}
        writer = PdfWriter()
        writer.append(reader)
        values = {str(key): "" if value is None else str(value) for key, value in data.items()}
        for page in writer.pages:
            if not page.get("/Annots"):
                continue
            writer.update_page_form_field_values(
                page, values, auto_regenerate=False
            )
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_rempli.pdf")
        )
        _write_pdf(writer, destination)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "fields_set": len(values),
            "message": f"Formulaire rempli ({len(values)} champ(s)) → {destination}",
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def compress(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        import pikepdf

        source = _resolve_path(raw_path)
        if not source.is_file():
            raise FileNotFoundError(source)
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_compresse.pdf")
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        original_size = source.stat().st_size
        temporary = _temporary(destination)

        def optimize() -> None:
            with pikepdf.open(str(source)) as document:
                document.save(
                    str(temporary),
                    compress_streams=True,
                    recompress_flate=True,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                )

        try:
            await asyncio.to_thread(optimize)
            if temporary.stat().st_size >= original_size:
                shutil.copy2(source, temporary)
                already_optimal = True
            else:
                already_optimal = False
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        new_size = destination.stat().st_size
        saved = (
            round((1 - new_size / original_size) * 100, 1)
            if original_size and not already_optimal
            else 0
        )
        result = {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "original_kb": round(original_size / 1024, 1),
            "compressed_kb": round(new_size / 1024, 1),
            "saved_pct": saved,
        }
        if already_optimal:
            result.update(
                {
                    "already_optimal": True,
                    "message": (
                        f"PDF déjà optimal ({round(original_size / 1024, 1)} Ko) "
                        f"— copie conservée → {destination}"
                    ),
                }
            )
        else:
            result["message"] = (
                f"{round(original_size / 1024, 1)} Ko → "
                f"{round(new_size / 1024, 1)} Ko ({saved}% gagné) → {destination}"
            )
        return result
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


async def add_page_numbers(args: dict) -> dict:
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"error": "Paramètre 'path' requis."}
    try:
        source = _resolve_path(raw_path)
        reader = _reader(source)
        total = len(reader.pages)
        label_format = str(args.get("format") or "Page {n} / {total}")
        position = str(args.get("position") or "bottom-center").lower()
        if position not in {
            "bottom-center", "bottom-right", "bottom-left",
            "top-center", "top-right", "top-left",
        }:
            return {"error": "Position invalide."}
        start = int(args.get("start_number", 1))
        font_size = int(args.get("font_size", 9))
        if not 6 <= font_size <= 200:
            return {"error": "'font_size' doit être compris entre 6 et 200."}
        writer = PdfWriter()
        for index, page in enumerate(reader.pages):
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            label = (
                label_format.replace("{n}", str(index + start))
                .replace("{page}", str(index + start))
                .replace("{total}", str(total))
            )

            def draw(canvas, page_width, page_height):
                canvas.setFont("Helvetica", font_size)
                margin = 24
                y = page_height - margin if position.startswith("top") else margin
                if position.endswith("right"):
                    canvas.drawRightString(page_width - margin, y, label)
                elif position.endswith("left"):
                    canvas.drawString(margin, y, label)
                else:
                    canvas.drawCentredString(page_width / 2, y, label)

            page.merge_page(_page_stamp(width, height, draw))
            writer.add_page(page)
        output_raw = str(args.get("output_path") or "").strip()
        destination = (
            _resolve_path(output_raw)
            if output_raw
            else source.with_name(f"{source.stem}_numerote.pdf")
        )
        _write_pdf(writer, destination)
        return {
            "success": True,
            "path": str(destination),
            "destination": str(destination),
            "pages": total,
            "message": f"Numérotation ajoutée sur {total} page(s) → {destination}",
        }
    except FileNotFoundError:
        return {"error": f"PDF introuvable : {_resolve_path(raw_path)}"}
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        return {"error": str(exc)}
