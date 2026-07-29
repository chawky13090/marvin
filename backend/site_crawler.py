"""Aspiration bornée, reprenable et SSRF-safe de sites Web publics."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

import outbound_http
from config import DATA_DIR


ROOT = Path(DATA_DIR) / "site_crawls"
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_USER_AGENT = "Mozilla/5.0 (compatible; MarvinSiteCrawler/2.494; +local-user-agent)"


def _canonical_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL HTTP(S) publique requise.")
    if parsed.username or parsed.password:
        raise ValueError("Les identifiants intégrés dans une URL sont interdits.")
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in _TRACKING_KEYS
        ],
        doseq=True,
    )
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), path, query, "")
    )


def _same_site(seed: str, candidate: str, include_subdomains: bool) -> bool:
    seed_host = (urlsplit(seed).hostname or "").casefold()
    candidate_host = (urlsplit(candidate).hostname or "").casefold()
    return candidate_host == seed_host or (
        include_subdomains and candidate_host.endswith("." + seed_host)
    )


def _safe_name(url: str) -> str:
    parsed = urlsplit(url)
    readable = re.sub(r"[^a-zA-Z0-9._-]+", "-", parsed.path.strip("/"))[:80]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{readable or 'index'}-{digest}.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _extract_html(
    body: bytes,
    *,
    page_url: str,
) -> tuple[str, str, list[str], str]:
    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "lxml")
    title = " ".join(soup.title.get_text(" ", strip=True).split()) if soup.title else ""
    canonical = ""
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical_tag:
        canonical = str(canonical_tag.get("href") or "").strip()
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if href and not href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            try:
                links.append(_canonical_url(urljoin(page_url, href)))
            except ValueError:
                continue
    for tag in soup(
        [
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
            "form",
            "iframe",
            "noscript",
            "svg",
            "button",
            "input",
            "select",
        ]
    ):
        tag.decompose()
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(id="content")
        or soup.find("body")
        or soup
    )
    text = "\n".join(
        line.strip()
        for line in main.get_text(separator="\n", strip=True).splitlines()
        if line.strip()
    )
    return title[:500], text, list(dict.fromkeys(links)), canonical


def _sitemap_urls(body: bytes, sitemap_url: str) -> tuple[list[str], list[str]]:
    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "xml")
    locations = [
        str(node.get_text(strip=True))
        for node in soup.find_all("loc")
        if node.get_text(strip=True)
    ]
    if soup.find("sitemapindex"):
        return [], [_canonical_url(urljoin(sitemap_url, value)) for value in locations]
    return [_canonical_url(urljoin(sitemap_url, value)) for value in locations], []


async def crawl_site(args: dict[str, Any]) -> dict[str, Any]:
    """Aspire un site public, persiste chaque page et renvoie un corpus LLM borné."""
    seed = _canonical_url(str(args.get("url") or ""))
    max_pages = max(1, min(int(args.get("max_pages", 250)), 5_000))
    max_depth = max(0, min(int(args.get("max_depth", 8)), 20))
    per_page_chars = max(
        1_000, min(int(args.get("per_page_chars", 20_000)), 100_000)
    )
    max_return_chars = max(
        5_000, min(int(args.get("max_return_chars", 120_000)), 500_000)
    )
    include_subdomains = bool(args.get("include_subdomains", False))
    use_sitemaps = bool(args.get("use_sitemaps", True))
    browser_fallback = bool(args.get("browser_fallback", True))
    resume = bool(args.get("resume", True))
    requested_job_id = str(args.get("job_id") or "").strip()
    job_id = requested_job_id or uuid.uuid4().hex
    if resume and not requested_job_id and ROOT.is_dir():
        candidates: list[tuple[float, str]] = []
        for candidate in list(ROOT.glob("*/state.json"))[:5_000]:
            try:
                saved = json.loads(candidate.read_text(encoding="utf-8"))
                if (
                    saved.get("seed_url") == seed
                    and saved.get("status") == "partial"
                    and saved.get("queue")
                ):
                    candidates.append(
                        (float(saved.get("updated_at") or 0), candidate.parent.name)
                    )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        if candidates:
            job_id = max(candidates)[1]
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", job_id):
        raise ValueError("job_id invalide.")

    job_dir = ROOT / job_id
    pages_dir = job_dir / "pages"
    state_path = job_dir / "state.json"
    seed_host = (urlsplit(seed).hostname or "").casefold()
    queue: deque[tuple[str, int]] = deque([(seed, 0)])
    queued = {seed}
    visited: set[str] = set()
    pages: list[dict[str, Any]] = []
    successful_urls: set[str] = set()
    failures: list[dict[str, Any]] = []
    started = time.time()
    if resume and state_path.is_file():
        try:
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            if saved.get("seed_url") == seed:
                queue = deque(
                    (str(item[0]), int(item[1]))
                    for item in saved.get("queue") or []
                    if isinstance(item, list) and len(item) == 2
                )
                visited = {str(item) for item in saved.get("visited") or []}
                queued = visited | {item[0] for item in queue}
                failures = list(saved.get("failures") or [])[-100:]
                for artifact in sorted(pages_dir.glob("*.json")):
                    record = json.loads(artifact.read_text(encoding="utf-8"))
                    pages.append(
                        {
                            "url": str(record.get("url") or ""),
                            "title": str(record.get("title") or ""),
                            "characters": int(record.get("characters") or 0),
                            "content": str(record.get("content") or "")[:per_page_chars],
                            "content_truncated": int(record.get("characters") or 0)
                            > per_page_chars,
                        }
                    )
                    successful_urls.add(str(record.get("url") or ""))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            queue = deque([(seed, 0)])
            queued = {seed}
            visited = set()
            pages = []
            successful_urls = set()
            failures = []

    if use_sitemaps and not visited:
        sitemap_queue = deque(
            [
                urljoin(seed, "/sitemap.xml"),
                urljoin(seed, "/sitemap_index.xml"),
            ]
        )
        seen_sitemaps: set[str] = set()
        while sitemap_queue and len(seen_sitemaps) < 50:
            sitemap_url = _canonical_url(sitemap_queue.popleft())
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)
            try:
                response = await outbound_http.fetch_public(
                    sitemap_url,
                    max_bytes=10_000_000,
                    timeout=30,
                    headers={"User-Agent": _USER_AGENT, "Accept": "application/xml,text/xml"},
                )
                if response.status_code >= 400:
                    continue
                page_urls, nested = _sitemap_urls(response.content, response.url)
                sitemap_queue.extend(nested)
                for candidate in page_urls:
                    if (
                        candidate not in queued
                        and _same_site(seed, candidate, include_subdomains)
                    ):
                        queue.append((candidate, 0))
                        queued.add(candidate)
            except (OSError, TypeError, ValueError, outbound_http.httpx.HTTPError):
                continue

    returned_chars = sum(len(page["content"]) for page in pages)
    if returned_chars > max_return_chars:
        remaining = max_return_chars
        for page in pages:
            page["content"] = page["content"][:remaining]
            page["content_truncated"] = page["characters"] > len(page["content"])
            remaining -= len(page["content"])
            if remaining <= 0:
                remaining = 0
        returned_chars = max_return_chars
    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            response = await outbound_http.fetch_public(
                url,
                max_bytes=10_000_000,
                timeout=60,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8",
                },
            )
            content_type = response.headers.get("content-type", "").casefold()
            if response.status_code in {401, 403, 429} and browser_fallback:
                try:
                    import web_browser

                    rendered = await web_browser.fetch_page(
                        response.url, timeout=60_000, max_chars=per_page_chars
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "url": url,
                            "status": response.status_code,
                            "browser_error": type(exc).__name__,
                        }
                    )
                    continue
                final_url = _canonical_url(str(rendered.get("url") or response.url))
                title = str(rendered.get("title") or "")[:500]
                text = str(rendered.get("text") or "")
                links = []
                for raw_link in rendered.get("links") or []:
                    try:
                        links.append(_canonical_url(str(raw_link)))
                    except ValueError:
                        continue
                canonical = ""
            elif response.status_code >= 400:
                failures.append({"url": url, "status": response.status_code})
                continue
            else:
                if "html" not in content_type:
                    failures.append({"url": url, "error": f"type ignoré: {content_type[:100]}"})
                    continue
                title, text, links, canonical = _extract_html(
                    response.content, page_url=response.url
                )
                final_url = _canonical_url(
                    canonical and urljoin(response.url, canonical) or response.url
                )
                if browser_fallback and len(links) < 2:
                    try:
                        import web_browser

                        rendered = await web_browser.fetch_page(
                            response.url,
                            timeout=60_000,
                            max_chars=per_page_chars,
                        )
                        rendered_links: list[str] = []
                        for raw_link in rendered.get("links") or []:
                            try:
                                rendered_links.append(
                                    _canonical_url(str(raw_link))
                                )
                            except ValueError:
                                continue
                        if len(rendered_links) > len(links):
                            links = rendered_links
                        rendered_text = str(rendered.get("text") or "")
                        if len(rendered_text) > len(text):
                            text = rendered_text
                            title = str(rendered.get("title") or title)[:500]
                            final_url = _canonical_url(
                                str(rendered.get("url") or final_url)
                            )
                    except Exception as exc:
                        failures.append(
                            {
                                "url": url,
                                "browser_fallback": "degraded",
                                "browser_error": type(exc).__name__,
                            }
                        )
            record = {
                "url": final_url,
                "title": title,
                "depth": depth,
                "characters": len(text),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "content": text,
            }
            if final_url not in successful_urls:
                successful_urls.add(final_url)
                _atomic_json(pages_dir / _safe_name(final_url), record)
                available = max_return_chars - returned_chars
                excerpt = text[: min(per_page_chars, max(0, available))]
                pages.append(
                    {
                        "url": final_url,
                        "title": title,
                        "characters": len(text),
                        "content": excerpt,
                        "content_truncated": len(excerpt) < len(text),
                    }
                )
                returned_chars += len(excerpt)
            if depth < max_depth:
                for candidate in links:
                    if (
                        candidate not in queued
                        and candidate not in visited
                        and _same_site(seed, candidate, include_subdomains)
                    ):
                        queue.append((candidate, depth + 1))
                        queued.add(candidate)
        except (OSError, TypeError, ValueError, outbound_http.httpx.HTTPError) as exc:
            failures.append({"url": url, "error": type(exc).__name__})
        finally:
            _atomic_json(
                state_path,
                {
                    "job_id": job_id,
                    "seed_url": seed,
                    "status": "running" if queue and len(visited) < max_pages else "completed",
                    "pages_succeeded": len(pages),
                    "pages_attempted": len(visited),
                    "pages_pending": len(queue),
                    "failures": failures[-100:],
                    "queue": list(queue),
                    "visited": sorted(visited),
                    "updated_at": time.time(),
                },
            )

    status = "partial" if queue else "completed"
    result = {
        "success": bool(pages),
        "job_id": job_id,
        "seed_url": seed,
        "domain": seed_host,
        "status": status,
        "pages_succeeded": len(pages),
        "pages_attempted": len(visited),
        "pages_pending": len(queue),
        "failures_count": len(failures),
        "failures": failures[:100],
        "pages": pages,
        "artifact_directory": str(job_dir.resolve()),
        "returned_characters": returned_chars,
        "duration_ms": round((time.time() - started) * 1000),
        "limits": {
            "max_pages": max_pages,
            "max_depth": max_depth,
            "per_page_chars": per_page_chars,
            "max_return_chars": max_return_chars,
            "browser_fallback": browser_fallback,
        },
    }
    _atomic_json(
        state_path,
        {
            **result,
            "pages": [],
            "queue": list(queue),
            "visited": sorted(visited),
            "updated_at": time.time(),
        },
    )
    return result
