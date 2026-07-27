"""Régressions déterministes du noyau PDF."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tool_domains import pdf_core
import tools


def _resolve(raw: str) -> str:
    return str(Path(raw).resolve())


def _create_pdf(path: Path, labels: list[str], *, title: str) -> None:
    document = canvas.Canvas(str(path))
    document.setTitle(title)
    document.setAuthor("Marvin")
    for label in labels:
        document.drawString(72, 760, label)
        document.showPage()
    document.save()


async def _run() -> None:
    pdf_core.configure(resolve_path=_resolve)
    assert pdf_core.parse_pages("1,3-4,3,999,bad", 4) == [0, 2, 3]
    assert pdf_core.parse_pages([2, 1, 2], 3) == [1, 0]

    with tempfile.TemporaryDirectory(prefix="marvin-pdf-core-") as temp:
        root = Path(temp)
        first = root / "first.pdf"
        second = root / "second.pdf"
        _create_pdf(first, ["Alpha", "Beta"], title="Premier")
        _create_pdf(second, ["Gamma"], title="Second")

        info = await pdf_core.info({"path": str(first)})
        assert info.get("success") is True, info
        assert info["pages"] == 2
        assert info["title"] == "Premier"
        assert info["author"] == "Marvin"

        read = await pdf_core.read(
            {"path": str(first), "pages": "2", "max_chars": 1000}
        )
        assert read.get("success") is True, read
        assert read["pages_read"] == 1
        assert "Beta" in read["text"]
        assert "Alpha" not in read["text"]
        invalid_chars = await pdf_core.read({"path": str(first), "max_chars": 0})
        assert "compris entre" in invalid_chars.get("error", "")

        merged_path = root / "merged.pdf"
        merged = await pdf_core.merge(
            {
                "sources": [str(first), str(second)],
                "output_path": str(merged_path),
            }
        )
        assert merged.get("success") is True, merged
        assert merged["pages"] == 3
        assert len(PdfReader(str(merged_path)).pages) == 3

        split_dir = root / "split"
        split = await pdf_core.split(
            {
                "path": str(merged_path),
                "pages": "1,3",
                "per_page": False,
                "output_dir": str(split_dir),
            }
        )
        assert split.get("success") is True, split
        assert len(PdfReader(split["path"]).pages) == 2

        per_page = await pdf_core.split(
            {
                "path": str(first),
                "per_page": True,
                "output_dir": str(root / "pages"),
            }
        )
        assert per_page["count"] == 2
        assert all(len(PdfReader(path).pages) == 1 for path in per_page["files"])

        rotated_path = root / "rotated.pdf"
        rotated = await pdf_core.rotate(
            {
                "path": str(first),
                "pages": "2",
                "angle": 90,
                "output_path": str(rotated_path),
            }
        )
        assert rotated.get("success") is True, rotated
        rotated_reader = PdfReader(str(rotated_path))
        assert rotated_reader.pages[0].rotation == 0
        assert rotated_reader.pages[1].rotation == 90

        encrypted_path = root / "encrypted.pdf"
        encrypted_writer = PdfWriter()
        encrypted_writer.add_blank_page(width=100, height=100)
        encrypted_writer.encrypt("secret")
        with encrypted_path.open("wb") as handle:
            encrypted_writer.write(handle)
        encrypted_info = await pdf_core.info({"path": str(encrypted_path)})
        assert encrypted_info.get("success") is True
        assert encrypted_info["encrypted"] is True
        assert encrypted_info["pages"] == 0
        assert encrypted_info["page_count_unavailable"] is True
        encrypted_read = await pdf_core.read({"path": str(encrypted_path)})
        assert "chiffré" in encrypted_read.get("error", "")

        assert not list(root.rglob(".*.tmp"))

    pdf_core.configure(resolve_path=tools._resolve_path)
    assert tools.execute_pdf_read is pdf_core.read
    assert tools.execute_pdf_info is pdf_core.info
    assert tools.execute_pdf_merge is pdf_core.merge
    assert tools.execute_pdf_split is pdf_core.split
    assert tools.execute_pdf_rotate is pdf_core.rotate


if __name__ == "__main__":
    asyncio.run(_run())
    print("PDF core domain tests passed.")
