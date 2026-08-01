"""Métadonnées bornées et cache privé des aperçus de sources Web."""

from __future__ import annotations

import asyncio
import hashlib
import io
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import outbound_http
from config import DATA_DIR


PREVIEW_CACHE_DIR = DATA_DIR / "cache" / "web-source-previews"
MAX_PREVIEW_BYTES = 4 * 1024 * 1024
MAX_CACHE_BYTES = 250 * 1024 * 1024
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/x-icon",
    "image/vnd.microsoft.icon",
}
ALLOWED_PAGE_TYPES = {"text/html", "application/xhtml+xml"}
_CACHE_WRITE_LOCK = asyncio.Lock()


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _public_url(value: Any, base_url: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = urljoin(base_url, raw)
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return candidate[:4_096]


def extract_soup_metadata(soup: Any, page_url: str) -> dict[str, str]:
    """Extrait uniquement des chaînes éditoriales ; aucun HTML n'est conservé."""
    def meta(*selectors: tuple[str, str]) -> str:
        for attribute, value in selectors:
            tag = soup.find("meta", attrs={attribute: value})
            if tag and tag.get("content"):
                return _text(tag.get("content"), 500)
        return ""

    image = meta(
        ("property", "og:image"),
        ("name", "twitter:image"),
        ("property", "twitter:image"),
    )
    favicon = ""
    for link in soup.find_all("link", href=True):
        relations = {str(item).casefold() for item in (link.get("rel") or [])}
        if "icon" in relations or "shortcut icon" in relations:
            favicon = _public_url(link.get("href"), page_url)
            break
    host = (urlsplit(page_url).hostname or "").removeprefix("www.")
    return {
        "image_url": _public_url(image, page_url),
        "favicon_url": favicon,
        "publisher": meta(("property", "og:site_name"), ("name", "application-name")) or host,
        "published_at": meta(
            ("property", "article:published_time"),
            ("name", "date"),
            ("name", "datePublished"),
        )[:80],
    }


def normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    """Contrat stable accepté par le frontend, compatible avec les anciennes sources."""
    url = _public_url(source.get("url"), str(source.get("url") or ""))
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    evidence = str(source.get("evidence_level") or "snippet_only")
    if evidence not in {"page_read", "snippet_only", "access_restricted", "rejected"}:
        evidence = "snippet_only"
    return {
        "id": _text(source.get("id") or source.get("citation"), 100),
        "title": _text(source.get("title") or url, 300),
        "url": url,
        "domain": _text(source.get("domain") or host, 255),
        "publisher": _text(source.get("publisher") or host, 160),
        "published_at": _text(source.get("published_at"), 80),
        "image_url": _public_url(source.get("image_url") or source.get("thumbnail"), url),
        "favicon_url": _public_url(source.get("favicon_url"), url),
        "evidence_level": evidence,
        "source_type": _text(source.get("source_type"), 80),
    }


def _prune_cache() -> None:
    files = sorted(
        (item for item in PREVIEW_CACHE_DIR.glob("*") if item.is_file()),
        key=lambda item: item.stat().st_mtime,
    )
    now = time.time()
    for item in list(files):
        if now - item.stat().st_mtime > CACHE_TTL_SECONDS:
            item.unlink(missing_ok=True)
            files.remove(item)
    total = sum(item.stat().st_size for item in files)
    for item in files:
        if total <= MAX_CACHE_BYTES:
            break
        size = item.stat().st_size
        item.unlink(missing_ok=True)
        total -= size


async def _fetch_preview_resource(url: str, *, accept: str) -> Any:
    try:
        return await outbound_http.fetch_public(
            url,
            max_bytes=MAX_PREVIEW_BYTES,
            timeout=7.0,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; MarvinSourcePreview/2.565)",
                "Accept": accept,
            },
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Aperçu distant indisponible.") from exc


def _origin_favicon(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"


async def _resolve_image_candidate(urls: list[str]) -> Any:
    unique_urls = list(dict.fromkeys(url for url in urls if url))[:3]

    async def fetch_candidate(url: str) -> Any:
        try:
            response = await _fetch_preview_resource(
                url,
                accept="image/avif,image/webp,image/png,image/jpeg,image/gif;q=0.8",
            )
        except ValueError:
            return None
        media_type = str(response.headers.get("content-type") or "").split(";", 1)[0].casefold()
        if response.status_code >= 400 or media_type not in ALLOWED_IMAGE_TYPES or not response.content:
            return None
        return response

    tasks = [asyncio.create_task(fetch_candidate(url)) for url in unique_urls]
    try:
        for task in asyncio.as_completed(tasks):
            response = await task
            if response is not None:
                return response
        return None
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def cache_preview(image_url: str) -> tuple[Path, str]:
    """Résout puis met en cache l’image d’une source publique, sans cookie ni SVG."""
    normalized_url = _public_url(image_url, image_url)
    if not normalized_url:
        raise ValueError("URL d’aperçu invalide.")
    digest = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    candidate = PREVIEW_CACHE_DIR / f"{digest}.webp"
    if candidate.is_file() and time.time() - candidate.stat().st_mtime <= CACHE_TTL_SECONDS:
        return candidate, "image/webp"

    response = await _fetch_preview_resource(
        normalized_url,
        accept="image/avif,image/webp,image/png,image/jpeg,image/gif,text/html;q=0.7",
    )
    media_type = str(response.headers.get("content-type") or "").split(";", 1)[0].casefold()
    if media_type == "image/svg+xml":
        raise ValueError("Type d’image non autorisé.")
    if response.status_code >= 400 or media_type in ALLOWED_PAGE_TYPES:
        from bs4 import BeautifulSoup

        metadata = {}
        if response.status_code < 400:
            soup = BeautifulSoup(response.content.decode("utf-8", errors="replace"), "lxml")
            metadata = extract_soup_metadata(soup, response.url)
        response = await _resolve_image_candidate(
            [
                str(metadata.get("image_url") or ""),
                str(metadata.get("favicon_url") or ""),
                _origin_favicon(response.url),
            ]
        )
        if response is None:
            raise ValueError("Cette page ne publie aucun aperçu visuel exploitable.")
        media_type = str(response.headers.get("content-type") or "").split(";", 1)[0].casefold()
    if media_type not in ALLOWED_IMAGE_TYPES or not response.content:
        raise ValueError("Type d’image non autorisé.")

    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(response.content)) as image:
            image.seek(0)
            if image.width * image.height > 25_000_000:
                raise ValueError("Dimensions d’image excessives.")
            image.thumbnail((1_200, 700), Image.Resampling.LANCZOS)
            rendered = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = io.BytesIO()
            rendered.save(output, format="WEBP", quality=82, method=4)
            preview_content = output.getvalue()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("Contenu d’image invalide.") from exc

    target = candidate
    temporary = PREVIEW_CACHE_DIR / f"{digest}.{uuid.uuid4().hex}.tmp"
    async with _CACHE_WRITE_LOCK:
        try:
            temporary.write_bytes(preview_content)
            temporary.replace(target)
            _prune_cache()
        finally:
            temporary.unlink(missing_ok=True)
    return target, "image/webp"
