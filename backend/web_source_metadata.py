"""Métadonnées bornées et cache privé des aperçus de sources Web."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import time
import uuid
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import outbound_http
from config import DATA_DIR


PREVIEW_CACHE_DIR = DATA_DIR / "cache" / "web-source-previews"
MAX_PREVIEW_BYTES = 4 * 1024 * 1024
MAX_CACHE_BYTES = 250 * 1024 * 1024
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
STALE_IF_ERROR_SECONDS = 30 * 24 * 60 * 60
NEGATIVE_CACHE_TTL_SECONDS = 15 * 60
MAX_METADATA_IMAGE_CANDIDATES = 8
QUALITY_GRACE_SECONDS = 0.7
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
_INFLIGHT_LOCK = asyncio.Lock()
_INFLIGHT: dict[str, asyncio.Task[tuple[Path, str]]] = {}
_LOGGER = logging.getLogger("marvin.web_source_preview")


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


def _json_ld_image_urls(soup: Any, page_url: str) -> list[str]:
    """Extrait des URL d'image JSON-LD sans interpréter ni exécuter le contenu."""
    candidates: list[str] = []
    visited = 0

    def visit(value: Any, depth: int = 0) -> None:
        nonlocal visited
        if depth > 8 or visited >= 256 or len(candidates) >= MAX_METADATA_IMAGE_CANDIDATES:
            return
        visited += 1
        if isinstance(value, list):
            for item in value[:32]:
                visit(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        if str(value.get("@type") or "").casefold() == "imageobject":
            for key in ("contentUrl", "url", "thumbnailUrl"):
                candidate = _public_url(value.get(key), page_url)
                if candidate:
                    candidates.append(candidate)
        for key in ("image", "thumbnailUrl", "primaryImageOfPage"):
            nested = value.get(key)
            if isinstance(nested, str):
                candidate = _public_url(nested, page_url)
                if candidate:
                    candidates.append(candidate)
            else:
                visit(nested, depth + 1)
        for key, nested in list(value.items())[:64]:
            if key not in {"image", "thumbnailUrl", "primaryImageOfPage"}:
                visit(nested, depth + 1)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"})[:8]:
        raw = script.string or script.get_text("", strip=True)
        if not raw or len(raw) > 256_000:
            continue
        try:
            visit(json.loads(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return list(dict.fromkeys(candidates))[:MAX_METADATA_IMAGE_CANDIDATES]


def _largest_srcset_url(value: Any, page_url: str) -> str:
    ranked: list[tuple[int, str]] = []
    for item in str(value or "").split(",")[:16]:
        parts = item.strip().split()
        if not parts:
            continue
        score = 1
        descriptor = parts[-1]
        if len(parts) > 1 and descriptor[:-1].isdigit() and descriptor[-1:] in {"w", "x"}:
            score = int(descriptor[:-1])
        candidate = _public_url(parts[0], page_url)
        if candidate:
            ranked.append((score, candidate))
    return max(ranked, default=(0, ""))[1]


def _content_image_urls(soup: Any, page_url: str) -> list[str]:
    """Sélection bornée d'images éditoriales, après les métadonnées explicites."""
    ranked: list[tuple[int, str]] = []
    reject_hints = {"avatar", "badge", "icon", "logo", "pixel", "spacer", "sprite", "tracking"}
    prefer_hints = {"article", "content", "featured", "gallery", "hero", "main", "photo"}
    for index, image in enumerate(soup.find_all("img")[:80]):
        source = (
            _largest_srcset_url(image.get("srcset") or image.get("data-srcset"), page_url)
            or _public_url(image.get("src") or image.get("data-src") or image.get("data-lazy-src"), page_url)
        )
        if not source:
            continue
        hints = " ".join(
            str(image.get(key) or "") for key in ("class", "id", "alt", "title", "role")
        ).casefold() + " " + source.casefold()
        if any(hint in hints for hint in reject_hints):
            continue
        try:
            width = int(str(image.get("width") or "0").removesuffix("px"))
            height = int(str(image.get("height") or "0").removesuffix("px"))
        except ValueError:
            width = height = 0
        if width and height and (width < 180 or height < 90):
            continue
        score = max(0, 80 - index)
        score += min(width * height // 10_000, 100)
        score += 80 if any(hint in hints for hint in prefer_hints) else 0
        ranked.append((score, source))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return list(dict.fromkeys(url for _, url in ranked))[:4]


def extract_soup_metadata(soup: Any, page_url: str) -> dict[str, Any]:
    """Extrait uniquement des chaînes éditoriales ; aucun HTML n'est conservé."""
    def meta(*selectors: tuple[str, str]) -> str:
        for attribute, value in selectors:
            tag = soup.find("meta", attrs={attribute: value})
            if tag and tag.get("content"):
                return _text(tag.get("content"), 500)
        return ""

    explicit_images = [
        meta(("property", "og:image:secure_url")),
        meta(("property", "og:image:url")),
        meta(("property", "og:image")),
        meta(("name", "twitter:image:src")),
        meta(("name", "twitter:image")),
        meta(("property", "twitter:image")),
    ]
    favicon = ""
    for link in soup.find_all("link", href=True):
        relations = {str(item).casefold() for item in (link.get("rel") or [])}
        if "image_src" in relations:
            explicit_images.append(str(link.get("href") or ""))
        if "icon" in relations or "shortcut icon" in relations:
            favicon = _public_url(link.get("href"), page_url)
    image_candidates = [
        candidate
        for candidate in (
            _public_url(value, page_url)
            for value in explicit_images + _json_ld_image_urls(soup, page_url) + _content_image_urls(soup, page_url)
        )
        if candidate
    ]
    image_candidates = list(dict.fromkeys(image_candidates))[:MAX_METADATA_IMAGE_CANDIDATES]
    host = (urlsplit(page_url).hostname or "").removeprefix("www.")
    return {
        "image_url": image_candidates[0] if image_candidates else "",
        "image_candidates": image_candidates,
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
        retention = NEGATIVE_CACHE_TTL_SECONDS if item.suffix == ".miss" else STALE_IF_ERROR_SECONDS
        if now - item.stat().st_mtime > retention:
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
                "User-Agent": "Mozilla/5.0 (compatible; MarvinSourcePreview/2.566)",
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
    unique_urls = list(dict.fromkeys(url for url in urls if url))[:MAX_METADATA_IMAGE_CANDIDATES]

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
        return url, response

    tasks = [asyncio.create_task(fetch_candidate(url)) for url in unique_urls]
    priority = {url: index for index, url in enumerate(unique_urls)}
    try:
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            successful = []
            for task in done:
                result = task.result()
                if result is not None:
                    successful.append(result)
            if not successful:
                continue
            if pending:
                grace_done, pending = await asyncio.wait(pending, timeout=QUALITY_GRACE_SECONDS)
                for task in grace_done:
                    result = task.result()
                    if result is not None:
                        successful.append(result)
            _url, response = min(successful, key=lambda item: priority[item[0]])
            return response
        return None
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _cache_preview_uncached(normalized_url: str, digest: str) -> tuple[Path, str]:
    started = time.perf_counter()
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    candidate = PREVIEW_CACHE_DIR / f"{digest}.webp"

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
            list(metadata.get("image_candidates") or [])
            + [str(metadata.get("favicon_url") or ""), _origin_favicon(response.url)]
        )
        if response is None:
            raise ValueError("Cette page ne publie aucun aperçu visuel exploitable.")
        media_type = str(response.headers.get("content-type") or "").split(";", 1)[0].casefold()
    if media_type not in ALLOWED_IMAGE_TYPES or not response.content:
        raise ValueError("Type d’image non autorisé.")

    from PIL import Image, UnidentifiedImageError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(response.content)) as image:
                image.seek(0)
                if image.width * image.height > 25_000_000:
                    raise ValueError("Dimensions d’image excessives.")
                image.thumbnail((1_200, 700), Image.Resampling.LANCZOS)
                rendered = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = io.BytesIO()
                rendered.save(output, format="WEBP", quality=82, method=4)
                preview_content = output.getvalue()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Contenu d’image invalide.") from exc

    target = candidate
    temporary = PREVIEW_CACHE_DIR / f"{digest}.{uuid.uuid4().hex}.tmp"
    async with _CACHE_WRITE_LOCK:
        try:
            temporary.write_bytes(preview_content)
            temporary.replace(target)
            (PREVIEW_CACHE_DIR / f"{digest}.miss").unlink(missing_ok=True)
            _prune_cache()
        finally:
            temporary.unlink(missing_ok=True)
    _LOGGER.info(
        "web_source_preview_resolved",
        extra={
            "event": "web_source_preview_resolved",
            "url_hash": digest[:12],
            "host": (urlsplit(normalized_url).hostname or "")[:253],
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    return target, "image/webp"


async def cache_preview(image_url: str) -> tuple[Path, str]:
    """Résout puis met en cache l’image d’une source publique, sans cookie ni SVG."""
    normalized_url = _public_url(image_url, image_url)
    if not normalized_url:
        raise ValueError("URL d’aperçu invalide.")
    digest = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    candidate = PREVIEW_CACHE_DIR / f"{digest}.webp"
    miss = PREVIEW_CACHE_DIR / f"{digest}.miss"
    candidate_age = time.time() - candidate.stat().st_mtime if candidate.is_file() else None
    stale_available = candidate_age is not None and candidate_age <= STALE_IF_ERROR_SECONDS
    if candidate_age is not None and candidate_age <= CACHE_TTL_SECONDS:
        return candidate, "image/webp"
    if miss.is_file() and time.time() - miss.stat().st_mtime <= NEGATIVE_CACHE_TTL_SECONDS:
        if stale_available:
            return candidate, "image/webp"
        raise ValueError("Aperçu temporairement indisponible (échec récent mémorisé).")

    async with _INFLIGHT_LOCK:
        task = _INFLIGHT.get(digest)
        if task is None:
            task = asyncio.create_task(_cache_preview_uncached(normalized_url, digest))
            _INFLIGHT[digest] = task
    try:
        return await asyncio.shield(task)
    except (OSError, TypeError, ValueError):
        temporary = PREVIEW_CACHE_DIR / f"{digest}.{uuid.uuid4().hex}.tmp"
        async with _CACHE_WRITE_LOCK:
            try:
                temporary.write_text("unavailable\n", encoding="utf-8")
                temporary.replace(miss)
                _prune_cache()
            finally:
                temporary.unlink(missing_ok=True)
        if stale_available:
            _LOGGER.info(
                "web_source_preview_stale_fallback",
                extra={"event": "web_source_preview_stale_fallback", "url_hash": digest[:12]},
            )
            return candidate, "image/webp"
        raise
    finally:
        if task.done():
            async with _INFLIGHT_LOCK:
                if _INFLIGHT.get(digest) is task:
                    _INFLIGHT.pop(digest, None)
