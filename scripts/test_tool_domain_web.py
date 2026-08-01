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
import research_swarm
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
                "unresponsive_engines": [["blocked", "access denied"]],
                "results": [
                    {
                        "title": f"Marvin Source {index}",
                        "url": f"https://example{index}.com/page",
                        "engines": ["bing", "google cse"],
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
        priority = await web.execute_web_search({
            "query": "Marvin",
            "max_results": 10,
            "categories": ["general", "social media"],
        })
    discovery = {
        "success": True,
        "provider": "SearXNG",
        "query": "site officiel France Travail",
        "search_query": "site officiel France Travail",
        "results": [
            {
                "title": "France Travail",
                "url": "https://www.francetravail.fr/accueil/",
                "snippet": "Site officiel",
            },
            {
                "title": "France Travail — Wikipédia",
                "url": "https://fr.wikipedia.org/wiki/France_Travail",
                "snippet": "Encyclopédie",
            },
            {
                "title": "France Travail recrute",
                "url": "https://recrute.francetravail.org/",
                "snippet": "Site de recrutement",
            },
        ],
    }
    with (
        patch.object(
            web,
            "execute_web_search",
            AsyncMock(return_value=discovery),
        ) as search_mock,
        patch.object(
            web.site_crawler,
            "crawl_site",
            AsyncMock(return_value={"success": True, "pages_succeeded": 12}),
        ) as crawl_site,
    ):
        crawled = await web.execute_web_site_crawl(
            {"site": "aspire le site France Travail"}
        )
    assert crawled["discovery"]["provider"] == "SearXNG"
    assert search_mock.await_args.args[0]["query"] == "site officiel France Travail"
    assert crawled["discovery"]["selected_url"].startswith(
        "https://www.francetravail.fr/"
    )
    assert crawl_site.await_args.args[0]["url"].startswith(
        "https://www.francetravail.fr/"
    )
    assert priority["provider"] == "SearXNG"
    request_params = searx_client.get.await_args.kwargs["params"]
    assert request_params["categories"] == "general,social media"
    assert priority["categories"] == ["general", "social media"]
    assert priority["results"][0]["engines"] == ["bing", "google cse"]
    assert priority["unresponsive_engines"] == [["blocked", "access denied"]]
    assert priority["degraded"] is True
    assert "snippets" in priority["evidence_notice"]
    ordered = web._filter_relevant_results(
        "site officiel France Travail",
        [
            {
                "title": "Accueil | France Travail",
                "url": "https://www.francetravail.fr/accueil/",
                "snippet": "",
            },
            {
                "title": "Site institutionnel officiel France Travail",
                "url": "https://www.francetravail.org/accueil/",
                "snippet": "",
            },
        ],
    )
    assert ordered[0]["url"] == "https://www.francetravail.fr/accueil/"
    assert priority["fallback_used"] is False
    assert priority["count"] == 10
    assert priority["provider_attempts"] == [
        {"provider": "SearXNG", "status": "succeeded"}
    ]

    class EmptySearxResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [], "unresponsive_engines": [["qwant", "CAPTCHA"]]}

    empty_cache: dict[object, object] = {}
    empty_client = SimpleNamespace(get=AsyncMock(return_value=EmptySearxResponse()))
    with patch("credentials_manager.get_credential", return_value="http://127.0.0.1:8080"):
        web.configure(
            generate=fake_generate,
            get_setting=lambda _key: 3,
            get_http_client=lambda: empty_client,
            cache_get=empty_cache.get,
            cache_set=empty_cache.__setitem__,
            net_error=lambda exc, what: {"error": str(exc), "resource": what},
        )
        empty = await web.execute_web_search({"query": "requête sans résultat unique"})
        cached_empty = await web.execute_web_search({"query": "requête sans résultat unique"})
    assert empty["success"] is True and empty["empty"] is True and empty["count"] == 0
    assert "error" not in empty and "warning" in empty
    assert cached_empty["cached"] is True
    assert empty_client.get.await_count == 1
    assert web._prepare_searxng_query(
        "Quel est le statut des feux de foret en France ?"
    ) == "feux de foret en France aujourd'hui en cours actualités"
    assert web._prepare_searxng_query(
        "recher sur le web les derniers infos sur les feux de foret en france"
    ) == "derniers infos sur les feux de foret en france"
    assert web._prepare_searxng_query(
        "Recherche sur le web via SearXNG les nouveautés officielles de Python 3.14. "
        "Donne un résumé court et cite les liens directs."
    ) == "nouveautés officielles de Python 3.14"
    assert web._prepare_searxng_query(
        'recherche sur le web "Chaouki Boussayri" site:linkedin.com'
    ) == '"Chaouki Boussayri" site:linkedin.com'
    assert web._clean_search_query(
        '"Chaouki Boussayri" OR "Chaouki Boussairi" site:linkedin.com'
    ) == '"Chaouki Boussayri" OR "Chaouki Boussairi" site:linkedin.com'
    assert web._infer_search_categories("Chaouki Boussayri") == (
        "general",
        "social media",
    )
    assert web._infer_search_categories(
        '"Chaouki Boussayri" OR "Chaouki Boussairi"'
    ) == ("general", "social media")
    assert web._infer_search_categories("meilleures baskets Skechers prix avis") == (
        "general",
        "images",
    )
    person_filtered = web._filter_relevant_results(
        '"Chaouki Boussayri" OR "Chaouki Boussairi" site:linkedin.com',
        [
            {
                "title": "Central Time",
                "url": "https://time.example",
                "snippet": "Current time or date",
            },
            {
                "title": "Boussairi Chaouki",
                "url": "https://social.example/profile",
                "snippet": "Profil public",
            },
            {
                "title": "Chaouki Loukili",
                "url": "https://linkedin.com/other",
                "snippet": "Autre personne",
            },
        ],
    )
    assert [item["url"] for item in person_filtered] == [
        "https://social.example/profile"
    ]
    invalid_category = await web.execute_web_search(
        {"query": "Marvin", "categories": ["inconnue"]}
    )
    assert "Catégorie SearXNG invalide" in invalid_category["error"]
    assert web._parse_research_queries(
        '["Python 3.14 official docs", "Python 3.14 release notes"]',
        fallback="nouveautés officielles de Python 3.14",
    ) == (
        "nouveautés officielles de Python 3.14",
        "Python 3.14 official docs",
        "Python 3.14 release notes",
    )
    filtered = web._filter_relevant_results(
        "feux de foret France",
        [
            {
                "title": "Statut, statue ou status : règle de français",
                "url": "https://grammar.example/statut",
                "snippet": "Définition et exemples de la langue française.",
            },
            {"title": "Incendies en France", "url": "https://fire.example", "snippet": ""},
        ],
    )
    assert [item["url"] for item in filtered] == ["https://fire.example"]
    python_filtered = web._filter_relevant_results(
        "Quelles sont les principales nouveautés officielles de Python 3.14 ?",
        [
            {
                "title": "Quel, quelle, quelles : règle et exercices",
                "url": "https://grammar.example/quelles",
                "snippet": "Grammaire française.",
            },
            {
                "title": "What's New In Python 3.14",
                "url": "https://docs.python.org/3.14/whatsnew/3.14.html",
                "snippet": "Python 3.14 release highlights.",
            },
        ],
    )
    assert [item["url"] for item in python_filtered] == [
        "https://docs.python.org/3.14/whatsnew/3.14.html"
    ]
    interleaved = web._interleave_search_results([
        {"results": [
            {"url": "https://generic.example/1"},
            {"url": "https://generic.example/2"},
        ]},
        {"results": [
            {"url": "https://official.example/1"},
            {"url": "https://generic.example/1"},
        ]},
    ])
    assert [item["url"] for item in interleaved] == [
        "https://generic.example/1",
        "https://official.example/1",
        "https://generic.example/2",
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
    deep_result = {
        "success": True,
        "engine_version": "v3",
        "answer": "Rapport vérifié.",
        "sources": [{"id": "source-1", "title": "Titre", "url": "https://source.example"}],
        "queries": [{"id": "query-1", "query": "KOIOS", "accepted_sources": 1}],
        "source_coverage": {
            "queries_executed": 100,
            "pages_read": 50,
            "unique_sources": 50,
        },
    }
    with (
        patch.object(web, "_priority_search", side_effect=priority_search),
        patch.dict(sys.modules, {"web_browser": browser_module}),
        patch.object(research_swarm, "execute", new=AsyncMock(return_value=deep_result)) as deep_execute,
    ):
        normal = await web.execute_web_research({"query": "KOIOS"})
        deep = await web.execute_web_deep_research({
            "query": "KOIOS",
            "max_rounds": 3,
            "min_rounds": 3,
        })
    assert normal["provider"] == "SearXNG"
    assert len(normal["sources"]) == 20
    assert normal["sources"][0]["evidence_level"] == "page_read"
    assert deep["engine_version"] == "v3"
    assert deep["source_coverage"]["queries_executed"] == 100
    assert deep_execute.await_args.kwargs["engine_version"] == "v3"
    assert deep_execute.await_args.kwargs["research_options"]["depth"] == "deep"

    html = (
        b"<html><head><title> Marvin Test </title>"
        b'<meta content="Description fiable" name="description">'
        b'<meta content="Marvin Labs" property="og:site_name">'
        b'<meta content="/preview.png" property="og:image">'
        b'<meta content="2026-08-01" property="article:published_time">'
        b'<link href="/favicon.ico" rel="icon">'
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
    assert browsed["evidence_level"] == "page_read"
    assert browsed["publisher"] == "Marvin Labs"
    assert browsed["image_url"] == "https://example.com/preview.png"
    assert browsed["favicon_url"] == "https://example.com/favicon.ico"
    assert browsed["published_at"] == "2026-08-01"
    assert tools.execute_url_analyze is web.execute_url_analyze

    facebook_login = outbound_http.PublicResponse(
        url=(
            "https://www.facebook.com/login/?next="
            "https%3A%2F%2Fwww.facebook.com%2Fgroups%2F373264892856568%2F"
        ),
        status_code=400,
        headers={"content-type": "text/html"},
        content=b"",
        elapsed_ms=20,
    )
    with patch.object(
        outbound_http,
        "fetch_public",
        new=AsyncMock(return_value=facebook_login),
    ):
        restricted = await web.execute_web_browse(
            {"url": "https://www.facebook.com/groups/373264892856568/"}
        )
    assert restricted["authentication_required"] is True
    assert restricted["access_limited"] is True
    assert restricted["retryable"] is False
    assert restricted["error_code"] == "AUTHENTICATION_REQUIRED"
    assert restricted["content"] == ""
    assert "n’a pas lu" in restricted["message"]

    restricted_browser_module = SimpleNamespace(
        fetch_text=AsyncMock(return_value={
            "success": False,
            "authentication_required": True,
            "access_limited": True,
            "retryable": False,
            "error_code": "AUTHENTICATION_REQUIRED",
            "message": "Facebook exige une session connectée. Marvin n’a pas lu le contenu de cette page.",
            "url": facebook_login.url,
            "title": "Log in to Facebook",
            "text": "",
        })
    )
    with patch.dict(sys.modules, {"web_browser": restricted_browser_module}):
        browser_restricted = await web.execute_web_browser_open({
            "url": "https://www.facebook.com/groups/373264892856568/"
        })
    assert browser_restricted["authentication_required"] is True
    assert browser_restricted["text"] == ""

    restricted_discovery = {
        "success": True,
        "provider": "SearXNG",
        "fallback_used": False,
        "provider_attempts": [{"provider": "SearXNG", "status": "succeeded"}],
        "results": [{
            "title": "Groupe Facebook",
            "url": "https://www.facebook.com/groups/373264892856568/",
            "snippet": "Extrait non vérifié",
        }],
    }
    with (
        patch.object(web, "_priority_search", AsyncMock(return_value=restricted_discovery)),
        patch.object(web, "_plan_research_queries", AsyncMock(return_value=("groupe",))),
        patch.dict(sys.modules, {"web_browser": restricted_browser_module}),
    ):
        restricted_research = await web.execute_web_research({"query": "groupe"})
    assert restricted_research["success"] is False
    assert restricted_research["authentication_required"] is True
    assert restricted_research["answer"] == ""
    assert restricted_research["sources"][0]["evidence_level"] == "access_restricted"

    names = [
        name.removeprefix("execute_")
        for name in dir(web)
        if name.startswith("execute_web_")
    ]
    assert len(names) == 6
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
