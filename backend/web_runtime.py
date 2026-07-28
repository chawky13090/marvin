"""Runtime partagé et réversible pour les clients HTTP et le cache Web."""

from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

import httpx


ClientFactory = Callable[[], httpx.AsyncClient]
Clock = Callable[[], float]


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(12.0, connect=4.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            )
        },
    )


class WebRuntime:
    """Possède le pool HTTP et un cache TTL/LRU borné."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 600.0,
        max_entries: int = 256,
        clock: Clock = time.monotonic,
        client_factory: ClientFactory = _default_client_factory,
    ) -> None:
        if not 1.0 <= ttl_seconds <= 86_400:
            raise ValueError("ttl_seconds doit être compris entre 1 et 86 400.")
        if not 1 <= max_entries <= 10_000:
            raise ValueError("max_entries doit être compris entre 1 et 10 000.")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._client_factory = client_factory
        self._client: httpx.AsyncClient | None = None
        self._client_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    def get_client(self) -> httpx.AsyncClient:
        with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = self._client_factory()
            return self._client

    async def close(self) -> None:
        """Détache puis ferme le client; un prochain appel le recréera proprement."""
        with self._client_lock:
            client = self._client
            self._client = None
        if client is not None and not client.is_closed:
            await client.aclose()

    def cache_get(self, key: Hashable) -> Any | None:
        now = self._clock()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            created_at, value = entry
            if now - created_at >= self._ttl_seconds:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return copy.deepcopy(value)

    def cache_set(self, key: Hashable, value: Any) -> None:
        now = self._clock()
        with self._cache_lock:
            self._cache[key] = (now, copy.deepcopy(value))
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    @property
    def cache_size(self) -> int:
        with self._cache_lock:
            return len(self._cache)


def is_offline_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "getaddrinfo",
            "name or service",
            "temporary failure",
            "connecterror",
            "connection refused",
            "network is unreachable",
            "no address associated",
            "timed out",
            "readtimeout",
            "connecttimeout",
            "[errno 11001]",
            "[errno -3]",
            "failed to establish",
            "max retries",
            "nodename nor servname",
        )
    )


def network_error(error: Exception, resource: str = "la ressource") -> dict[str, Any]:
    if is_offline_error(error):
        return {
            "error": (
                f"Pas de connexion internet (ou {resource} injoignable). "
                "Vérifiez votre réseau puis réessayez."
            ),
            "offline": True,
        }
    return {"error": str(error)}


runtime = WebRuntime()
get_http_client = runtime.get_client
cache_get = runtime.cache_get
cache_set = runtime.cache_set
close = runtime.close
clear_cache = runtime.clear_cache
