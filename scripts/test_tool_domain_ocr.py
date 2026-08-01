"""Régressions déterministes du domaine OCR."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tool_domains import ocr
import tools


def _resolve(raw: str) -> str:
    return str(Path(raw).resolve())


async def _run() -> None:
    requests: list[tuple[str, str, dict | None]] = []

    async def requester(
        method: str, path: str, *, timeout: float, payload: dict | None = None
    ) -> dict:
        requests.append((method, path, payload))
        if path == "/api/tags":
            return {"models": [{"name": "qwen2.5:7b"}]}
        return {"response": "Texte extrait"}

    ocr.configure(
        resolve_path=_resolve,
        ollama_url="http://127.0.0.1:11434",
        requester=requester,
    )
    with tempfile.TemporaryDirectory(prefix="marvin-ocr-") as temp:
        root = Path(temp)
        image_path = root / "large.png"
        Image.new("RGB", (2400, 120), "white").save(image_path)

        with (
            patch.object(
                ocr.cloud_routing,
                "resolve_model",
                return_value="modele-vision-inconnu",
            ),
            patch.object(ocr.cloud_routing, "is_cloud_model", return_value=False),
        ):
            result = await ocr.extract(
                {
                    "image_path": str(image_path),
                    "model": "modele-vision-inconnu",
                    "prompt": "Lis le texte.",
                }
            )
        assert result.get("success") is True, result
        assert result["model"] == "qwen3.5:2b"
        assert result["text"] == "Texte extrait"
        assert result["resized_for_speed"] is True
        generate_payload = next(
            payload for _, path, payload in requests if path == "/api/generate"
        )
        assert generate_payload is not None
        assert generate_payload["stream"] is False
        assert len(generate_payload["images"]) == 1

        invalid = root / "not-image.txt"
        invalid.write_text("not an image", encoding="utf-8")
        with (
            patch.object(ocr.cloud_routing, "resolve_model", return_value="llava-phi3"),
            patch.object(ocr.cloud_routing, "is_cloud_model", return_value=False),
        ):
            invalid_result = await ocr.extract({"image_path": str(invalid)})
        assert "image reconnue" in invalid_result.get("error", "")

        with patch.object(
            ocr.cloud_routing,
            "resolve_model",
            side_effect=ocr.cloud_routing.CloudOnlyModelUnavailable(
                "Aucun modèle vision Cloud disponible"
            ),
        ):
            cloud_only = await ocr.extract({"image_path": str(image_path)})
        assert cloud_only.get("cloud_only") is True
        assert "Cloud" in cloud_only.get("error", "")

        missing = await ocr.extract({"image_path": ""})
        assert "requis" in missing.get("error", "")

    ocr.configure(
        resolve_path=tools._resolve_path,
        ollama_url=tools.OLLAMA_URL,
    )
    assert tools.execute_ocr_extract is ocr.extract


if __name__ == "__main__":
    asyncio.run(_run())
    print("OCR tool domain tests passed.")
