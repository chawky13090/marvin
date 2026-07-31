"""Inventaire et téléchargement bornés des images de pages Web publiques."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from PIL import Image

import outbound_http
from config import DATA_DIR


PathResolver = Callable[[str], str]
_resolver: PathResolver | None = None
_ROOT = Path(DATA_DIR) / "web_media"
_IMAGE_MIMES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_EXPECTED_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


def configure(*, resolve_path: PathResolver) -> None:
    global _resolver
    _resolver = resolve_path


def _candidate_urls(body: bytes, page_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "lxml")
    found: list[dict[str, str]] = []

    def add(raw: object, *, kind: str, alt: str = "") -> None:
        value = str(raw or "").strip()
        if not value or value.startswith(("data:", "blob:", "javascript:")):
            return
        url = urljoin(page_url, value)
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            found.append({"url": url, "kind": kind, "alt": alt[:500]})

    for tag in soup.find_all("img"):
        alt = str(tag.get("alt") or "")
        for attribute in ("src", "data-src", "data-lazy-src", "data-original"):
            add(tag.get(attribute), kind="image", alt=alt)
        for attribute in ("srcset", "data-srcset"):
            for item in str(tag.get(attribute) or "").split(","):
                add(item.strip().split(" ", 1)[0], kind="srcset", alt=alt)
    for tag in soup.find_all("source"):
        for item in str(tag.get("srcset") or tag.get("data-srcset") or "").split(","):
            add(item.strip().split(" ", 1)[0], kind="picture")
    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or "").casefold()
        if key in {"og:image", "og:image:url", "twitter:image"}:
            add(meta.get("content"), kind="social")
    for link in soup.find_all("link", href=True):
        relations = " ".join(str(item) for item in (link.get("rel") or [])).casefold()
        if "icon" in relations:
            add(link.get("href"), kind="icon")
    for tag in soup.find_all(style=True):
        for match in _CSS_URL_RE.finditer(str(tag.get("style") or "")):
            add(match.group(2), kind="background")
    for style in soup.find_all("style"):
        for match in _CSS_URL_RE.finditer(style.get_text(" ", strip=True)):
            add(match.group(2), kind="background")
    unique: dict[str, dict[str, str]] = {}
    for item in found:
        unique.setdefault(item["url"], item)
    return list(unique.values())


def _crawl_urls(job_id: str, limit: int) -> list[str]:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", job_id):
        raise ValueError("crawl_job_id invalide.")
    pages_dir = Path(DATA_DIR) / "site_crawls" / job_id / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"Crawl introuvable : {job_id}")
    urls: list[str] = []
    for artifact in sorted(pages_dir.glob("*.json"))[:limit]:
        record = json.loads(artifact.read_text(encoding="utf-8"))
        value = str(record.get("url") or "").strip()
        if value:
            urls.append(value)
    return urls


def _output_directory(value: str, run_id: str) -> Path:
    if value:
        if _resolver is None:
            raise RuntimeError("Le domaine Web média n'est pas configuré.")
        output = Path(_resolver(value))
    else:
        output = _ROOT / run_id
    output.mkdir(parents=True, exist_ok=True)
    return output


async def extract(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    crawl_job_id = str(args.get("crawl_job_id") or "").strip()
    if not url and not crawl_job_id:
        return {"error": "Fournir 'url' ou 'crawl_job_id'."}
    try:
        max_pages = max(1, min(int(args.get("max_pages", 25)), 100))
        max_files = max(1, min(int(args.get("max_files", 50)), 200))
        max_total_bytes = max(
            1_000_000, min(int(args.get("max_total_bytes", 50_000_000)), 200_000_000)
        )
        min_width = max(1, min(int(args.get("min_width", 200)), 20_000))
        min_height = max(1, min(int(args.get("min_height", 120)), 20_000))
        browser_fallback = bool(args.get("browser_fallback", True))
    except (TypeError, ValueError):
        return {"error": "Bornes numériques invalides."}
    run_id = uuid.uuid4().hex
    try:
        pages = _crawl_urls(crawl_job_id, max_pages) if crawl_job_id else [url]
        output = _output_directory(str(args.get("output_dir") or "").strip(), run_id)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"error": str(exc)}

    candidates: list[dict[str, str]] = []
    page_failures: list[dict[str, str]] = []
    for page_url in pages[:max_pages]:
        try:
            response = await outbound_http.fetch_public(
                page_url,
                max_bytes=5_000_000,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; MarvinMedia/2.529)"},
            )
            if response.status_code >= 400:
                page_failures.append({"url": page_url, "error": f"HTTP {response.status_code}"})
                continue
            page_candidates = _candidate_urls(response.content, response.url)
            for item in page_candidates:
                candidates.append({**item, "page_url": response.url})
            if browser_fallback and len(page_candidates) < 3:
                try:
                    import web_browser

                    rendered = await web_browser.extract_media_urls(response.url)
                    for item in rendered.get("media") or []:
                        if not isinstance(item, dict):
                            continue
                        value = str(item.get("url") or "").strip()
                        if value.startswith(("http://", "https://")):
                            candidates.append({
                                "url": value,
                                "kind": str(item.get("kind") or "rendered")[:40],
                                "alt": str(item.get("alt") or "")[:500],
                                "page_url": str(rendered.get("url") or response.url),
                            })
                except Exception as exc:
                    page_failures.append({
                        "url": page_url,
                        "error": f"browser_fallback:{type(exc).__name__}",
                    })
        except (OSError, ValueError, outbound_http.httpx.HTTPError) as exc:
            page_failures.append({"url": page_url, "error": type(exc).__name__})

    unique: dict[str, dict[str, str]] = {}
    for item in candidates:
        unique.setdefault(item["url"], item)
    downloaded: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    total_bytes = 0
    for item in list(unique.values()):
        if len(downloaded) >= max_files or total_bytes >= max_total_bytes:
            break
        try:
            response = await outbound_http.fetch_public(
                item["url"],
                max_bytes=min(10_000_000, max_total_bytes - total_bytes),
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; MarvinMedia/2.529)"},
            )
            mime = response.headers.get("content-type", "").split(";", 1)[0].casefold()
            suffix = _IMAGE_MIMES.get(mime)
            if response.status_code >= 400 or not suffix:
                raise ValueError(f"type ou statut refusé: {mime or response.status_code}")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(response.content)) as image:
                    width, height = image.size
                    actual_format = str(image.format or "").upper()
                    if actual_format != _EXPECTED_FORMATS[mime]:
                        raise ValueError(
                            f"MIME incohérent : {mime} contient {actual_format or 'inconnu'}"
                        )
                    if width * height > 40_000_000:
                        raise ValueError("Image refusée : plus de 40 millions de pixels.")
                    image.verify()
            if width < min_width or height < min_height:
                continue
            digest = hashlib.sha256(response.content).hexdigest()
            path = output / f"{digest[:16]}{suffix}"
            if not path.exists():
                temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
                temporary.write_bytes(response.content)
                os.replace(temporary, path)
            total_bytes += len(response.content)
            downloaded.append({
                **item,
                "url": response.url,
                "path": str(path.resolve()),
                "mime": mime,
                "width": width,
                "height": height,
                "size_bytes": len(response.content),
                "sha256": digest,
            })
        except (OSError, ValueError, outbound_http.httpx.HTTPError) as exc:
            failures.append({"url": item["url"][:2_000], "error": str(exc)[:200]})

    manifest = {
        "version": "1.0",
        "created_at": time.time(),
        "crawl_job_id": crawl_job_id,
        "pages_scanned": len(pages[:max_pages]),
        "candidates_found": len(unique),
        "downloaded": downloaded,
        "failures": failures[:100],
        "page_failures": page_failures[:100],
    }
    manifest_path = output / "manifest.json"
    temporary_manifest = manifest_path.with_suffix(".json.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary_manifest, manifest_path)
    succeeded = bool(downloaded)
    return {
        "success": succeeded,
        "verified": succeeded,
        "crawl_job_id": crawl_job_id,
        "pages_scanned": manifest["pages_scanned"],
        "candidates_found": len(unique),
        "downloaded_count": len(downloaded),
        "total_bytes": total_bytes,
        "output_directory": str(output.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "images": downloaded,
        "failures_count": len(failures) + len(page_failures),
        "artifacts": [
            {"path": str(manifest_path.resolve()), "type": "manifest", "format": "json"},
            *[
                {"path": item["path"], "type": "image", "format": item["mime"]}
                for item in downloaded
            ],
        ],
        "message": f"{len(downloaded)} image(s) vérifiée(s) extraite(s) vers {output}",
        **({"error": "Aucune image compatible n'a pu être vérifiée."} if not succeeded else {}),
    }
