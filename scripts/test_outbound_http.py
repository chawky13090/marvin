"""Tests déterministes du transport HTTP sortant anti-SSRF."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import outbound_http


class FakeClient:
    def __init__(self, responses: list[tuple[int, dict[str, str], bytes]], **_kwargs):
        self.responses = responses
        self.requests: list[httpx.Request] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def build_request(self, method: str, url: str, headers: dict[str, str]):
        return httpx.Request(method, url, headers=headers)

    async def send(self, request: httpx.Request, **_kwargs):
        self.requests.append(request)
        status, headers, content = self.responses.pop(0)
        return httpx.Response(status, headers=headers, content=content, request=request)


async def _resolver(hostname: str, _port: int) -> list[str]:
    return {
        "public.example": ["93.184.216.34"],
        "localhost": ["127.0.0.1"],
        "127.0.0.1": ["127.0.0.1"],
    }[hostname]


async def main() -> None:
    fake = FakeClient([(200, {"content-type": "text/plain"}, b"ok")])
    with patch.object(outbound_http.httpx, "AsyncClient", return_value=fake):
        response = await outbound_http.fetch_public(
            "https://public.example/path?q=1", resolver=_resolver
        )
    assert response.status_code == 200 and response.content == b"ok"
    assert str(fake.requests[0].url) == "https://93.184.216.34/path?q=1"
    assert fake.requests[0].headers["host"] == "public.example"
    assert fake.requests[0].extensions["sni_hostname"] == "public.example"

    redirect = FakeClient([(302, {"location": "http://localhost/admin"}, b"")])
    with patch.object(outbound_http.httpx, "AsyncClient", return_value=redirect):
        try:
            await outbound_http.fetch_public(
                "https://public.example/start", resolver=_resolver
            )
        except ValueError as exc:
            assert "non publique" in str(exc)
        else:
            raise AssertionError("Une redirection vers localhost doit être refusée.")
    assert len(redirect.requests) == 1

    oversized = FakeClient([(200, {}, b"123456")])
    with patch.object(outbound_http.httpx, "AsyncClient", return_value=oversized):
        try:
            await outbound_http.fetch_public(
                "https://public.example/", max_bytes=5, resolver=_resolver
            )
        except ValueError as exc:
            assert "dépasse" in str(exc)
        else:
            raise AssertionError("Une réponse hors budget doit être refusée.")

    for unsafe in (
        "http://127.0.0.1/",
        "http://user:pass@public.example/",
        "https://public.example:8443/",
    ):
        try:
            await outbound_http.fetch_public(unsafe, resolver=_resolver)
        except ValueError:
            pass
        else:
            raise AssertionError(f"URL dangereuse acceptée : {unsafe}")


if __name__ == "__main__":
    asyncio.run(main())
    print("Outbound HTTP OK - IP épinglée, redirections SSRF et budgets.")
