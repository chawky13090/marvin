"""Régressions déterministes des traitements PDF avancés."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tool_domains import pdf_advanced
import database as db
import tools


def _resolve(raw: str) -> str:
    return str(Path(raw).resolve())


def _create_pdf(path: Path, embedded_image: Path, *, scanned: bool = False) -> None:
    document = canvas.Canvas(str(path))
    if scanned:
        document.drawImage(ImageReader(str(embedded_image)), 72, 500, 200, 100)
        document.showPage()
    else:
        document.drawString(72, 760, "Première page avec suffisamment de texte intégré.")
        document.drawImage(ImageReader(str(embedded_image)), 72, 580, 120, 60)
        document.acroForm.textfield(
            name="client",
            tooltip="Client",
            x=72,
            y=520,
            width=180,
            height=24,
        )
        document.showPage()
        document.drawString(72, 760, "Deuxième page avec suffisamment de texte intégré.")
        document.showPage()
    document.save()


async def _run() -> None:
    generator_calls: list[dict] = []

    async def generate_text(prompt: str, **kwargs) -> str:
        generator_calls.append({"prompt": prompt, **kwargs})
        return "Texte OCR simulé"

    pdf_advanced.configure(
        resolve_path=_resolve,
        text_generator=generate_text,
        get_setting=lambda key: {"ocr_max_pages": 15, "ocr_scale": 2.0}.get(key),
    )
    with tempfile.TemporaryDirectory(prefix="marvin-pdf-advanced-") as temp:
        root = Path(temp)
        embedded = root / "embedded.png"
        Image.new("RGB", (160, 80), "navy").save(embedded)
        source = root / "source.pdf"
        _create_pdf(source, embedded)

        watermark_path = root / "watermarked.pdf"
        watermark = await pdf_advanced.watermark(
            {
                "path": str(source),
                "text": "CONFIDENTIEL",
                "output_path": str(watermark_path),
            }
        )
        assert watermark.get("success") is True, watermark
        assert len(PdfReader(str(watermark_path)).pages) == 2

        protected_path = root / "protected.pdf"
        protected = await pdf_advanced.protect(
            {
                "path": str(source),
                "password": "test-secret",
                "output_path": str(protected_path),
            }
        )
        assert protected.get("success") is True, protected
        assert PdfReader(str(protected_path)).is_encrypted

        extracted_dir = root / "extracted"
        extracted = await pdf_advanced.extract_images(
            {"path": str(source), "output_dir": str(extracted_dir)}
        )
        assert extracted.get("success") is True, extracted
        assert extracted["count"] >= 1
        assert all(Path(path).is_file() for path in extracted["files"])

        rendered_dir = root / "rendered"
        rendered = await pdf_advanced.to_images(
            {
                "path": str(source),
                "pages": "2",
                "dpi": 96,
                "output_dir": str(rendered_dir),
            }
        )
        assert rendered.get("success") is True, rendered
        assert rendered["count"] == 1
        with Image.open(rendered["path"]) as image:
            assert image.width > 0 and image.height > 0

        text_output = root / "ocr.txt"
        integrated_ocr = await pdf_advanced.ocr(
            {"path": str(source), "output_path": str(text_output)}
        )
        assert integrated_ocr.get("success") is True, integrated_ocr
        assert integrated_ocr["ocr_pages"] == 0
        assert "Première page" in text_output.read_text(encoding="utf-8")

        scanned = root / "scanned.pdf"
        _create_pdf(scanned, embedded, scanned=True)
        visual_ocr = await pdf_advanced.ocr(
            {"path": str(scanned), "max_pages": 1}
        )
        assert visual_ocr.get("success") is True, visual_ocr
        assert visual_ocr["ocr_pages"] == 1
        assert "Texte OCR simulé" in visual_ocr["text"]
        assert generator_calls[-1]["images"]

        fields = await pdf_advanced.form_fields({"path": str(source)})
        assert fields.get("success") is True, fields
        assert any(field["name"] == "client" for field in fields["fields"])

        filled_path = root / "filled.pdf"
        filled = await pdf_advanced.fill_form(
            {
                "path": str(source),
                "data": {"client": "KOIOS"},
                "output_path": str(filled_path),
            }
        )
        assert filled.get("success") is True, filled
        assert PdfReader(str(filled_path)).get_fields()["client"]["/V"] == "KOIOS"
        unknown = await pdf_advanced.fill_form(
            {"path": str(source), "data": {"unknown": "value"}}
        )
        assert "inconnu" in unknown.get("error", "")

        compressed_path = root / "compressed.pdf"
        compressed = await pdf_advanced.compress(
            {"path": str(source), "output_path": str(compressed_path)}
        )
        assert compressed.get("success") is True, compressed
        assert compressed_path.is_file()
        assert len(PdfReader(str(compressed_path)).pages) == 2

        numbered_path = root / "numbered.pdf"
        numbered = await pdf_advanced.add_page_numbers(
            {"path": str(source), "output_path": str(numbered_path)}
        )
        assert numbered.get("success") is True, numbered
        numbered_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(str(numbered_path)).pages
        )
        assert "Page 1 / 2" in numbered_text
        assert not list(root.rglob(".*.tmp"))

    pdf_advanced.configure(
        resolve_path=tools._resolve_path,
        text_generator=tools._ollama_generate,
        get_setting=db.get_setting,
    )
    assert tools.execute_pdf_watermark is pdf_advanced.watermark
    assert tools.execute_pdf_protect is pdf_advanced.protect
    assert tools.execute_pdf_extract_images is pdf_advanced.extract_images
    assert tools.execute_pdf_to_images is pdf_advanced.to_images
    assert tools.execute_pdf_ocr is pdf_advanced.ocr
    assert tools.execute_pdf_form_fields is pdf_advanced.form_fields
    assert tools.execute_pdf_fill_form is pdf_advanced.fill_form
    assert tools.execute_pdf_compress is pdf_advanced.compress
    assert tools.execute_pdf_add_page_numbers is pdf_advanced.add_page_numbers


if __name__ == "__main__":
    asyncio.run(_run())
    print("Advanced PDF domain tests passed.")
