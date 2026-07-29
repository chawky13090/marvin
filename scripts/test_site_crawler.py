"""Tests déterministes du crawler de sites Marvin."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import outbound_http  # noqa: E402
import site_crawler  # noqa: E402


PAGES = {
    "https://example.com/sitemap.xml": (
        200,
        "application/xml",
        b"""<?xml version="1.0"?><urlset>
        <url><loc>https://example.com/</loc></url>
        <url><loc>https://example.com/about/</loc></url>
        </urlset>""",
    ),
    "https://example.com/sitemap_index.xml": (404, "text/plain", b"missing"),
    "https://example.com/": (
        200,
        "text/html",
        b"<html><title>Home</title><main>Welcome</main>"
        b'<a href="/contact/?utm_source=test">Contact</a></html>',
    ),
    "https://example.com/about/": (
        200,
        "text/html",
        b"<html><title>About</title><main>About us</main></html>",
    ),
    "https://example.com/contact/": (
        200,
        "text/html",
        b"<html><title>Contact</title><main>Contact us</main></html>",
    ),
}


async def fake_fetch(url: str, **_: object) -> outbound_http.PublicResponse:
    status, content_type, body = PAGES[url]
    return outbound_http.PublicResponse(
        url=url,
        status_code=status,
        headers={"content-type": content_type},
        content=body,
        elapsed_ms=1,
    )


async def main() -> None:
    original_fetch = site_crawler.outbound_http.fetch_public
    with tempfile.TemporaryDirectory() as directory:
        site_crawler.ROOT = Path(directory)
        site_crawler.outbound_http.fetch_public = fake_fetch
        try:
            result = await site_crawler.crawl_site(
                {
                    "url": "https://example.com",
                    "max_pages": 10,
                    "max_depth": 3,
                    "job_id": "test-crawl-job",
                    "browser_fallback": False,
                }
            )
        finally:
            site_crawler.outbound_http.fetch_public = original_fetch

        assert result["success"] is True
        assert result["status"] == "completed"
        assert result["pages_succeeded"] == 3
        assert result["pages_pending"] == 0
        assert {page["url"] for page in result["pages"]} == {
            "https://example.com/",
            "https://example.com/about/",
            "https://example.com/contact/",
        }
        assert (Path(directory) / "test-crawl-job" / "state.json").is_file()
        assert len(list((Path(directory) / "test-crawl-job" / "pages").glob("*.json"))) == 3

        site_crawler.outbound_http.fetch_public = fake_fetch
        partial = await site_crawler.crawl_site(
            {
                "url": "https://example.com",
                "max_pages": 1,
                "job_id": "test-resume-job",
                "browser_fallback": False,
            }
        )
        assert partial["status"] == "partial" and partial["pages_pending"] > 0
        resumed = await site_crawler.crawl_site(
            {
                "url": "https://example.com",
                "max_pages": 10,
                "job_id": "test-resume-job",
                "resume": True,
                "browser_fallback": False,
            }
        )
        assert resumed["status"] == "completed"
        assert resumed["pages_succeeded"] == 3
        site_crawler.outbound_http.fetch_public = original_fetch

    try:
        await site_crawler.crawl_site({"url": "https://user:secret@example.com/private"})
    except ValueError:
        pass
    else:
        raise AssertionError("Les identifiants intégrés à l'URL devaient être refusés.")

    print("OK - site crawler")


if __name__ == "__main__":
    asyncio.run(main())
