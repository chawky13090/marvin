"""Régressions de l'extraction bornée des médias Web."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from outbound_http import PublicResponse
from tool_domains import web_media


def _image_bytes(size: tuple[int, int]) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, (82, 112, 96)).save(stream, format="JPEG")
    return stream.getvalue()


async def run() -> None:
    html = b"""
    <html><head>
      <meta property="og:image" content="/social.jpg">
      <link rel="icon" href="/tiny.jpg">
      <style>.hero{background-image:url('/background.jpg')}</style>
    </head><body>
      <img src="/main.jpg" alt="Vue d'Aix"
           srcset="/small.jpg 320w, /large.jpg 1600w">
      <img data-src="/lazy.jpg" alt="Lazy">
    </body></html>
    """
    large = _image_bytes((1600, 900))
    normal = _image_bytes((800, 500))
    tiny = _image_bytes((32, 32))

    async def fake_fetch(url: str, **_kwargs) -> PublicResponse:
        if url == "https://example.test/":
            return PublicResponse(url=url, status_code=200, headers={"content-type": "text/html"}, content=html, elapsed_ms=1)
        body = tiny if url.endswith(("tiny.jpg", "small.jpg")) else large if url.endswith("large.jpg") else normal
        return PublicResponse(url=url, status_code=200, headers={"content-type": "image/jpeg"}, content=body, elapsed_ms=1)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        web_media.configure(resolve_path=lambda value: str(Path(value).resolve()))
        with patch.object(web_media.outbound_http, "fetch_public", side_effect=fake_fetch):
            result = await web_media.extract({
                "url": "https://example.test/",
                "output_dir": str(root / "media"),
                "max_files": 20,
                "min_width": 200,
                "min_height": 120,
            })
        assert result["success"] is True
        assert result["verified"] is True
        assert result["candidates_found"] == 7
        assert result["downloaded_count"] == 5
        assert result["failures_count"] == 0
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        assert len(manifest["downloaded"]) == 5
        assert {item["kind"] for item in manifest["downloaded"]} >= {
            "image", "srcset", "social", "background"
        }
        assert all(Path(item["path"]).is_file() for item in manifest["downloaded"])
        assert all(len(item["sha256"]) == 64 for item in manifest["downloaded"])

        missing = await web_media.extract({})
        assert "url" in missing["error"]

        async def mismatched_fetch(url: str, **_kwargs) -> PublicResponse:
            if url == "https://example.test/":
                one = b'<img src="/fake.png" width="800" height="500">'
                return PublicResponse(url=url, status_code=200, headers={"content-type": "text/html"}, content=one, elapsed_ms=1)
            return PublicResponse(url=url, status_code=200, headers={"content-type": "image/png"}, content=normal, elapsed_ms=1)

        with patch.object(web_media.outbound_http, "fetch_public", side_effect=mismatched_fetch):
            mismatch = await web_media.extract({
                "url": "https://example.test/",
                "output_dir": str(root / "mismatch"),
                "browser_fallback": False,
            })
        assert mismatch["success"] is False
        assert mismatch["verified"] is False
        assert "Aucune image" in mismatch["error"]


if __name__ == "__main__":
    asyncio.run(run())
    print("Web Media OK - découverte, validation, manifeste, bornes et provenance.")
