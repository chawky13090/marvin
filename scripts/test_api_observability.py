"""Régressions de corrélation et métriques HTTP sans réseau."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import api_observability


async def scenario() -> None:
    api_observability.reset_for_tests()
    sent = []

    async def app(scope, receive, send):
        assert scope["state"]["request_id"] == "client-request-123"
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b"failure"})

    middleware = api_observability.ApiObservabilityMiddleware(app)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/jobs/123/550e8400-e29b-41d4-a716-446655440000",
        "headers": [(b"x-request-id", b"client-request-123")],
        "state": {},
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    original_write = api_observability._store.write
    api_observability._store.write = lambda *args, **kwargs: True
    try:
        await middleware(scope, receive, send)
    finally:
        api_observability._store.write = original_write
    assert dict(sent[0]["headers"])[b"x-request-id"] == b"client-request-123"
    assert dict(sent[0]["headers"])[b"server-timing"].startswith(b"app;dur=")
    metrics = api_observability.snapshot()
    assert metrics["requests"] == 1
    assert metrics["errors_5xx"] == 1
    assert metrics["status_classes"] == {"5xx": 1}
    assert metrics["top_routes"][0]["route"] == "GET /api/jobs/{id}/{id}"
    assert api_observability.normalize_request_id("bad value") != "bad value"
    assert len(api_observability.normalize_request_id(None)) == 32


def main() -> int:
    asyncio.run(scenario())
    print("API Observability OK - corrélation, latence, cardinalité et erreurs bornées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
