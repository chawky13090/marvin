"""Tests déterministes du runtime HTTP/cache partagé."""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
import web_runtime


class FakeClient:
    def __init__(self) -> None:
        self.is_closed = False
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1
        self.is_closed = True


async def main() -> None:
    now = [10.0]
    created: list[FakeClient] = []

    def factory():
        client = FakeClient()
        created.append(client)
        return client

    runtime = web_runtime.WebRuntime(
        ttl_seconds=10,
        max_entries=2,
        clock=lambda: now[0],
        client_factory=factory,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        clients = list(pool.map(lambda _: runtime.get_client(), range(32)))
    assert len({id(client) for client in clients}) == 1
    assert len(created) == 1

    runtime.cache_set("a", {"items": [1]})
    first = runtime.cache_get("a")
    first["items"].append(2)
    assert runtime.cache_get("a") == {"items": [1]}
    runtime.cache_set("b", 2)
    assert runtime.cache_get("a") == {"items": [1]}
    runtime.cache_set("c", 3)
    assert runtime.cache_get("b") is None
    assert runtime.cache_size == 2
    now[0] = 20.0
    assert runtime.cache_get("a") is None

    await runtime.close()
    await runtime.close()
    assert created[0].close_count == 1
    assert runtime.get_client() is not created[0]
    assert len(created) == 2
    await runtime.close()

    assert tools._get_http_client is web_runtime.get_http_client
    assert tools._wcache_get is web_runtime.cache_get
    assert tools._wcache_set is web_runtime.cache_set
    assert tools._net_error is web_runtime.network_error
    main_source = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert main_source.index(
        'await shutdown_runtime.run("workers", supervisor.shutdown)'
    ) < main_source.index(
        'await shutdown_runtime.run("web-http", web_runtime.close)'
    )
    offline = web_runtime.network_error(RuntimeError("getaddrinfo failed"), "test")
    assert offline["offline"] is True and "test" in offline["error"]
    assert "offline" not in web_runtime.network_error(RuntimeError("HTTP 500"))
    print("Web Runtime OK - pool, fermeture, concurrence, TTL, LRU et façades.")


if __name__ == "__main__":
    asyncio.run(main())
