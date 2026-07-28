"""Régressions OCR écran : limites, provenance, repli et nettoyage."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cloud_routing
import tools
from tool_domains import screen_ocr


def capture(region: dict[str, int] | None) -> tuple[Image.Image, list[int]]:
    size = (
        (region["width"], region["height"])
        if region is not None
        else (2_560, 1_440)
    )
    return Image.new("RGB", size, "white"), [size[0], size[1]]


async def main() -> None:
    temporary_files: list[str] = []

    async def vision(args: dict[str, Any]) -> dict[str, Any]:
        temporary_files.append(args["image_path"])
        assert Path(args["image_path"]).is_file()
        return {
            "success": True,
            "text": "Texte vision",
            "model": "vision-model:cloud",
        }

    with tempfile.TemporaryDirectory() as directory:
        screen_ocr.configure(
            vision_ocr=vision,
            is_cloud_model=lambda model: model.endswith(":cloud"),
            output_dir=directory,
            capture=capture,
            tesseract_ocr=lambda _image, _language: "Texte local",
            id_factory=lambda: "fixed",
        )
        result = await screen_ocr.extract(
            {"method": "vision", "save": True}
        )
        assert result["success"] is True
        assert result["text"] == "Texte vision"
        assert result["model"] == "vision-model:cloud"
        assert result["cloud"] is True
        assert result["resized_for_ocr"] is True
        assert result["processed_size"] == [1_920, 1_080]
        assert result["rollback"]["available"] is True
        assert Path(result["saved_to"]).is_file()
        assert temporary_files and not Path(temporary_files[0]).exists()

        async def failed_vision(_args: dict[str, Any]) -> dict[str, Any]:
            return {"error": "vision indisponible"}

        screen_ocr.configure(
            vision_ocr=failed_vision,
            is_cloud_model=lambda _model: False,
            output_dir=directory,
            capture=capture,
            tesseract_ocr=lambda _image, _language: "Repli local",
        )
        fallback = await screen_ocr.extract({"method": "auto"})
        assert fallback["method"] == "tesseract"
        assert fallback["text"] == "Repli local"
        assert fallback["attempts"][0]["status"] == "error"
        assert fallback["attempts"][1]["status"] == "ok"

        screen_ocr.configure(
            vision_ocr=failed_vision,
            is_cloud_model=lambda _model: False,
            output_dir=directory,
            capture=capture,
            tesseract_ocr=lambda _image, _language: "",
        )
        unavailable = await screen_ocr.extract({"method": "auto"})
        assert unavailable["success"] is False
        assert "error" in unavailable
        assert len(unavailable["attempts"]) == 2

        assert "region" in (
            await screen_ocr.extract({"region": [0, 0, -1, 10]})
        )["error"]
        assert "booléen" in (
            await screen_ocr.extract({"save": "oui"})
        )["error"]
        assert "auto" in (
            await screen_ocr.extract({"method": "inconnu"})
        )["error"]
        assert "4000" in (
            await screen_ocr.extract({"prompt": "x" * 4_001})
        )["error"]

    screen_ocr.configure(
        vision_ocr=tools.execute_ocr_extract,
        is_cloud_model=cloud_routing.is_cloud_model,
        output_dir=tools._SYSTEM_PATHS["desktop"],
    )
    assert tools.execute_screen_ocr is screen_ocr.extract
    assert tools.TOOLS_REGISTRY["screen_ocr"] is screen_ocr.extract


if __name__ == "__main__":
    asyncio.run(main())
    print("Screen OCR OK - limites, provenance, repli, sauvegarde et nettoyage.")
