"""Régressions déterministes du domaine d'outils Web."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

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
