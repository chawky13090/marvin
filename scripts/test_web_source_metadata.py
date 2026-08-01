from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup
from PIL import Image
import io


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import outbound_http
import web_source_metadata as metadata


async def _run() -> None:
    soup = BeautifulSoup(
        """
        <html><head>
          <meta property="og:image" content="/hero.jpg">
          <meta property="og:site_name" content="Agence Exemple">
          <meta property="article:published_time" content="2026-08-01T09:00:00Z">
          <link rel="icon" href="/favicon.png">
        </head></html>
        """,
        "lxml",
    )
    extracted = metadata.extract_soup_metadata(soup, "https://news.example/article")
    assert extracted["image_url"] == "https://news.example/hero.jpg"
    assert extracted["favicon_url"] == "https://news.example/favicon.png"
    assert extracted["publisher"] == "Agence Exemple"

    normalized = metadata.normalize_source({
        "url": "https://www.example.com/article",
        "title": "  Titre   vérifié ",
        "thumbnail": "/preview.png",
        "evidence_level": "page_read",
    })
    assert normalized["domain"] == "example.com"
    assert normalized["image_url"] == "https://www.example.com/preview.png"
    assert normalized["evidence_level"] == "page_read"
    assert metadata.normalize_source({"url": "https://example.com"})["image_url"] == ""

    source_image = io.BytesIO()
    Image.new("RGB", (32, 20), "#70747a").save(source_image, format="PNG")
    image_response = outbound_http.PublicResponse(
        url="https://cdn.example/preview.png",
        status_code=200,
        headers={"content-type": "image/png"},
        content=source_image.getvalue(),
        elapsed_ms=5,
    )
    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-") as directory:
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)
        try:
            with patch.object(
                metadata.outbound_http,
                "fetch_public",
                new=AsyncMock(return_value=image_response),
            ) as fetch:
                path, media_type = await metadata.cache_preview(image_response.url)
                cached_path, cached_type = await metadata.cache_preview(image_response.url)
            assert path == cached_path and path.is_file()
            assert media_type == cached_type == "image/webp"
            assert fetch.await_count == 1
            with Image.open(path) as rendered:
                assert rendered.format == "WEBP"
                assert rendered.size == (32, 20)
        finally:
            metadata.PREVIEW_CACHE_DIR = old_cache

    svg_response = outbound_http.PublicResponse(
        url="https://cdn.example/vector.svg",
        status_code=200,
        headers={"content-type": "image/svg+xml"},
        content=b"<svg/>",
        elapsed_ms=5,
    )
    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-") as directory:
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)
        try:
            with patch.object(
                metadata.outbound_http,
                "fetch_public",
                new=AsyncMock(return_value=svg_response),
            ):
                try:
                    await metadata.cache_preview(svg_response.url)
                except ValueError as exc:
                    assert "non autorisé" in str(exc)
                else:
                    raise AssertionError("Un SVG distant ne doit pas être mis en cache.")
        finally:
            metadata.PREVIEW_CACHE_DIR = old_cache

    with patch.object(
        metadata.outbound_http,
        "fetch_public",
        new=AsyncMock(side_effect=OSError("transport interne")),
    ):
        try:
            await metadata.cache_preview("https://example.com/unavailable.png")
        except ValueError as exc:
            assert str(exc) == "Aperçu distant indisponible."
            assert "transport interne" not in str(exc)
        else:
            raise AssertionError("Une panne de transport doit être rendue sans détail interne.")


if __name__ == "__main__":
    asyncio.run(_run())
    print("Métadonnées et cache des sources Web OK")
