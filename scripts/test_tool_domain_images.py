"""Régressions déterministes du domaine Images."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tool_domains import images
import tools


def _resolve(raw: str) -> str:
    return str(Path(raw).resolve())


async def _run() -> None:
    images.configure(resolve_path=_resolve)
    with tempfile.TemporaryDirectory(prefix="marvin-images-") as temp:
        root = Path(temp)
        source = root / "source.png"
        Image.new("RGBA", (400, 200), (30, 90, 180, 180)).save(source)

        info = await images.info({"path": str(source)})
        assert info.get("success") is True, info
        assert (info["width"], info["height"], info["format"]) == (400, 200, "PNG")

        resized_path = root / "resized.jpg"
        resized = await images.resize(
            {
                "path": str(source),
                "output_path": str(resized_path),
                "width": 100,
                "format": "JPEG",
                "quality": 90,
            }
        )
        assert resized.get("success") is True, resized
        assert resized["resized"] == {"width": 100, "height": 50}
        with Image.open(resized_path) as result:
            assert result.size == (100, 50)
            assert result.mode == "RGB"

        cropped_path = root / "cropped.png"
        cropped = await images.crop(
            {
                "path": str(source),
                "output_path": str(cropped_path),
                "aspect": "1:1",
            }
        )
        assert cropped.get("success") is True, cropped
        assert cropped["size"] == [200, 200]
        invalid_crop = await images.crop(
            {"path": str(source), "left": 300, "right": 100}
        )
        assert "Boîte de rognage invalide" in invalid_crop.get("error", "")

        rotated_path = root / "rotated.png"
        rotated = await images.rotate(
            {
                "path": str(source),
                "output_path": str(rotated_path),
                "angle": 90,
            }
        )
        assert rotated.get("success") is True, rotated
        with Image.open(rotated_path) as result:
            assert result.size == (200, 400)

        compressed_path = root / "compressed.webp"
        compressed = await images.compress(
            {
                "path": str(source),
                "output_path": str(compressed_path),
                "format": "WEBP",
                "quality": 70,
            }
        )
        assert compressed.get("success") is True, compressed
        with Image.open(compressed_path) as result:
            assert result.format == "WEBP"

        pdf_path = root / "images.pdf"
        pdf = await images.images_to_pdf(
            {
                "sources": [str(source), str(rotated_path)],
                "output_path": str(pdf_path),
                "dpi": 150,
            }
        )
        assert pdf.get("success") is True, pdf
        assert len(PdfReader(str(pdf_path)).pages) == 2

        nested_source = root / "nested-source"
        nested = nested_source / "level"
        nested.mkdir(parents=True)
        Image.new("RGB", (80, 40), "red").save(nested / "nested.jpg")
        batch_output = root / "batch-output"
        batch = await images.batch(
            {
                "directory": str(nested_source),
                "output_dir": str(batch_output),
                "recursive": True,
                "operation": "resize",
                "width": 40,
            }
        )
        assert batch.get("success") is True, batch
        assert batch["processed"] == 1
        with Image.open(batch_output / "nested.jpg") as result:
            assert result.size == (40, 20)

        invalid_operation = await images.batch(
            {"directory": str(nested_source), "operation": "unknown"}
        )
        assert "Opération invalide" in invalid_operation.get("error", "")

    images.configure(resolve_path=tools._resolve_path)
    assert tools.execute_image_info is images.info
    assert tools.execute_image_resize is images.resize
    assert tools.execute_images_to_pdf is images.images_to_pdf
    assert tools.execute_image_crop is images.crop
    assert tools.execute_image_rotate is images.rotate
    assert tools.execute_image_compress is images.compress
    assert tools.execute_image_batch is images.batch


if __name__ == "__main__":
    asyncio.run(_run())
    print("Image tool domain tests passed.")
