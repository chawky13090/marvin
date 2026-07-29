"""Régressions déterministes du domaine d'outils Web."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import outbound_http
import tools
from tool_domains import web


async def _run() -> None:
    cache: dict[object, object] = {}

    async def fake_generate(prompt: str, **_kwargs) -> str:
        return "Synthèse vérifiée."

    web.configure(
        generate=fake_generate,
        get_setting=lambda _key: 2,
        get_http_client=lambda: None,
        cache_get=cache.get,
        cache_set=cache.__setitem__,
        net_error=lambda exc, what: {"error": str(exc), "resource": what},
    )

    invalid_provider = await web.execute_web_search(
        {"query": "Marvin", "provider": "inconnu"}
    )
    assert "Provider invalide" in invalid_provider["error"]
    invalid_count = await web.execute_web_search(
        {"query": "Marvin", "max_results": "beaucoup"}
    )
    assert "max_results" in invalid_count["error"]
    invalid_chars = await web.execute_web_browse(
        {"url": "example.com", "max_chars": "beaucoup"}
    )
    assert "max_chars" in invalid_chars["error"]
    assert (await web.execute_web_search({"query": ""}))["error"] == "Requête vide"

    class SearxResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": f"Source {index}",
                        "url": f"https://example{index}.com/page",
                        "content": f"Fait vérifié {index}",
                    }
                    for index in range(1, 11)
                ]
            }

    searx_client = SimpleNamespace(get=AsyncMock(return_value=SearxResponse()))
    with patch("credentials_manager.get_credential", side_effect=lambda key: (
        "http://127.0.0.1:8080" if key == "searxng_url" else None
    )):
        web.configure(
            generate=fake_generate,
            get_setting=lambda _key: 3,
            get_http_client=lambda: searx_client,
            cache_get=lambda _key: None,
            cache_set=lambda _key, _value: None,
            net_error=lambda exc, what: {"error": str(exc), "resource": what},
        )
        priority = await web.execute_web_search({"query": "Marvin", "max_results": 10})
    assert priority["provider"] == "SearXNG"
    assert priority["fallback_used"] is False
    assert priority["count"] == 10
    assert priority["provider_attempts"] == [
        {"provider": "SearXNG", "status": "succeeded"}
    ]

    async def priority_search(query: str, max_results: int) -> dict:
        query_id = sum(map(ord, query))
        return {
            "success": True,
            "provider": "SearXNG",
            "fallback_used": False,
            "provider_attempts": [{"provider": "SearXNG", "status": "succeeded"}],
            "results": [
                {
                    "title": f"{query} source {index}",
                    "url": f"https://source-{query_id}-{index}.example/page",
                    "snippet": f"Information {index} pour {query}",
                }
                for index in range(1, max_results + 1)
            ],
        }

    async def fetch_text(url: str, **_kwargs) -> dict:
        return {"url": url, "title": "Titre", "text": f"Contenu détaillé de {url}"}

    browser_module = SimpleNamespace(fetch_text=fetch_text)
    with (
        patch.object(web, "_priority_search", side_effect=priority_search),
        patch.dict(sys.modules, {"web_browser": browser_module}),
    ):
        normal = await web.execute_web_research({"query": "KOIOS"})
        deep = await web.execute_web_deep_research({
            "query": "KOIOS",
            "max_rounds": 3,
            "min_rounds": 3,
        })
    assert normal["provider"] == "SearXNG"
    assert len(normal["sources"]) == 10
    assert deep["provider_priority"] == "SearXNG"
    assert deep["fallback_used"] is False
    assert deep["rounds"] == 3
    assert len(deep["sources"]) == 18
    assert len(deep["search_receipts"]) == 3

    html = (
        b"<html><head><title> Marvin Test </title>"
        b'<meta content="Description fiable" name="description">'
        b'<link href="https://example.com/canonical" rel="canonical">'
        b"</head><body><main>Contenu public</main></body></html>"
    )
    public_response = outbound_http.PublicResponse(
        url="https://example.com/final",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=html,
        elapsed_ms=12,
    )
    with patch.object(
        outbound_http,
        "fetch_public",
        new=AsyncMock(return_value=public_response),
    ):
        analyzed = await web.execute_url_analyze({"url": "example.com"})
        browsed = await web.execute_web_browse(
            {"url": "example.com", "max_chars": 1000}
        )
    assert analyzed["title"] == "Marvin Test"
    assert analyzed["description"] == "Description fiable"
    assert analyzed["canonical"] == "https://example.com/canonical"
    assert browsed["content"] == "Contenu public"
    assert tools.execute_url_analyze is web.execute_url_analyze

    names = [
        name.removeprefix("execute_")
        for name in dir(web)
        if name.startswith("execute_web_")
    ]
    assert len(names) == 5
    for public_name in names:
        implementation = getattr(web, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation
    assert tools.TOOLS_REGISTRY["billing_market_research"] is (
        tools.execute_billing_market_research
    )


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine Web OK")
