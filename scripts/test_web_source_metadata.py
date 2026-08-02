from __future__ import annotations

import asyncio
import os
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
          <meta property="og:image:secure_url" content="https://cdn.example/secure-hero.jpg">
          <meta property="og:site_name" content="Agence Exemple">
          <meta property="article:published_time" content="2026-08-01T09:00:00Z">
          <link rel="icon" href="/favicon.png">
        </head></html>
        """,
        "lxml",
    )
    extracted = metadata.extract_soup_metadata(soup, "https://news.example/article")
    assert extracted["image_url"] == "https://cdn.example/secure-hero.jpg"
    assert extracted["image_candidates"][:2] == [
        "https://cdn.example/secure-hero.jpg",
        "https://news.example/hero.jpg",
    ]
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

    structured = BeautifulSoup(
        """
        <html><head>
          <script type="application/ld+json">
            {"@type":"NewsArticle","image":{"@type":"ImageObject","contentUrl":"/schema-photo.jpg"}}
          </script>
        </head><body>
          <img class="site-logo" src="/logo.png" width="64" height="64">
          <img class="article-photo" srcset="/small.jpg 320w, /large.jpg 1280w" alt="Photo du reportage">
        </body></html>
        """,
        "lxml",
    )
    structured_metadata = metadata.extract_soup_metadata(structured, "https://news.example/report")
    assert structured_metadata["image_candidates"][:2] == [
        "https://news.example/schema-photo.jpg",
        "https://news.example/large.jpg",
    ]

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

    page_response = outbound_http.PublicResponse(
        url="https://news.example/article",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=b'<html><head><meta property="og:image" content="https://cdn.example/preview.png"></head></html>',
        elapsed_ms=5,
    )
    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-") as directory:
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)
        try:
            with patch.object(
                metadata.outbound_http,
                "fetch_public",
                new=AsyncMock(side_effect=[page_response, image_response]),
            ) as fetch:
                path, media_type = await metadata.cache_preview(page_response.url)
            assert path.is_file() and media_type == "image/webp"
            # Page HTML + image OpenGraph + favicon d'origine lancés en parallèle.
            assert fetch.await_count == 3
        finally:
            metadata.PREVIEW_CACHE_DIR = old_cache

    blocked_image_response = outbound_http.PublicResponse(
        url="https://cdn.example/blocked.jpg",
        status_code=403,
        headers={"content-type": "image/jpeg"},
        content=b"",
        elapsed_ms=5,
    )
    favicon_response = outbound_http.PublicResponse(
        url="https://news.example/favicon.png",
        status_code=200,
        headers={"content-type": "image/png"},
        content=source_image.getvalue(),
        elapsed_ms=5,
    )
    fallback_page_response = outbound_http.PublicResponse(
        url="https://news.example/fallback",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=(
            b'<html><head><meta property="og:image" content="https://cdn.example/blocked.jpg">'
            b'<link rel="icon" href="/favicon.png"></head></html>'
        ),
        elapsed_ms=5,
    )

    async def fetch_with_fallback(url: str, **_kwargs):
        responses = {
            fallback_page_response.url: fallback_page_response,
            blocked_image_response.url: blocked_image_response,
            favicon_response.url: favicon_response,
            "https://news.example/favicon.ico": blocked_image_response,
        }
        return responses[url]

    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-") as directory:
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)
        try:
            with patch.object(metadata.outbound_http, "fetch_public", new=fetch_with_fallback):
                path, media_type = await metadata.cache_preview(fallback_page_response.url)
            assert path.is_file() and media_type == "image/webp"
        finally:
            metadata.PREVIEW_CACHE_DIR = old_cache

    forbidden_page_response = outbound_http.PublicResponse(
        url="https://private.example/article",
        status_code=403,
        headers={"content-type": "text/html"},
        content=b"",
        elapsed_ms=5,
    )
    origin_favicon_response = outbound_http.PublicResponse(
        url="https://private.example/favicon.ico",
        status_code=200,
        headers={"content-type": "image/x-icon"},
        content=source_image.getvalue(),
        elapsed_ms=5,
    )

    async def fetch_origin_favicon(url: str, **_kwargs):
        if url == forbidden_page_response.url:
            return forbidden_page_response
        if url == origin_favicon_response.url:
            return origin_favicon_response
        raise AssertionError(f"URL inattendue: {url}")

    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-") as directory:
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)
        try:
            with patch.object(metadata.outbound_http, "fetch_public", new=fetch_origin_favicon):
                path, media_type = await metadata.cache_preview(forbidden_page_response.url)
            assert path.is_file() and media_type == "image/webp"
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

    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-transport-") as directory, patch.object(
        metadata.outbound_http, "fetch_public", new=AsyncMock(side_effect=OSError("transport interne")),
    ):
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)
        try:
            await metadata.cache_preview("https://example.com/unavailable.png")
        except ValueError as exc:
            assert str(exc) == "Aperçu distant indisponible."
            assert "transport interne" not in str(exc)
        else:
            raise AssertionError("Une panne de transport doit être rendue sans détail interne.")
        finally:
            metadata.PREVIEW_CACHE_DIR = old_cache

    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-negative-") as directory:
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)
        failed_fetch = AsyncMock(side_effect=OSError("transport interne"))
        try:
            with patch.object(metadata.outbound_http, "fetch_public", new=failed_fetch):
                for expected in ("Aperçu distant indisponible.", "échec récent mémorisé"):
                    try:
                        await metadata.cache_preview("https://example.com/negative.png")
                    except ValueError as exc:
                        assert expected in str(exc)
                    else:
                        raise AssertionError("Un échec récent doit rester négativement mis en cache.")
            assert failed_fetch.await_count == 1
        finally:
            metadata.PREVIEW_CACHE_DIR = old_cache

    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-stale-") as directory:
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)
        try:
            with patch.object(metadata.outbound_http, "fetch_public", new=AsyncMock(return_value=image_response)):
                stale_path, _ = await metadata.cache_preview("https://cdn.example/stale.png")
            stale_time = stale_path.stat().st_mtime - metadata.CACHE_TTL_SECONDS - 60
            os.utime(stale_path, (stale_time, stale_time))
            with patch.object(metadata.outbound_http, "fetch_public", new=AsyncMock(side_effect=OSError("panne"))):
                fallback_path, fallback_type = await metadata.cache_preview("https://cdn.example/stale.png")
            assert fallback_path == stale_path and fallback_type == "image/webp"
        finally:
            metadata.PREVIEW_CACHE_DIR = old_cache

    with tempfile.TemporaryDirectory(prefix="marvin-source-preview-singleflight-") as directory:
        old_cache = metadata.PREVIEW_CACHE_DIR
        metadata.PREVIEW_CACHE_DIR = Path(directory)

        async def delayed_image(_url: str, **_kwargs):
            await asyncio.sleep(0.02)
            return image_response

        try:
            with patch.object(metadata.outbound_http, "fetch_public", new=AsyncMock(side_effect=delayed_image)) as fetch:
                first, second = await asyncio.gather(
                    metadata.cache_preview("https://cdn.example/shared.png"),
                    metadata.cache_preview("https://cdn.example/shared.png"),
                )
            assert first == second
            assert fetch.await_count == 1
        finally:
            metadata.PREVIEW_CACHE_DIR = old_cache


if __name__ == "__main__":
    asyncio.run(_run())
    print("Métadonnées et cache des sources Web OK")
