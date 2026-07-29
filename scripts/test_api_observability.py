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
    api_observability.record_access_decision("csrf_rejected")
    api_observability.record_access_decision("capability_required")
    api_observability.record_idempotency_decision("completed")
    api_observability.record_idempotency_decision("replayed")
    metrics = api_observability.snapshot()
    assert metrics["access_decisions"] == {
        "capability_required": 1,
        "csrf_rejected": 1,
    }
    assert metrics["idempotency_decisions"] == {
        "completed": 1,
        "replayed": 1,
    }
    for invalid, recorder in (
        ("raw-session-value", api_observability.record_access_decision),
        ("raw-idempotency-key", api_observability.record_idempotency_decision),
    ):
        try:
            recorder(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Une étiquette non bornée a été acceptée.")

    api_observability.reset_for_tests()
    api_observability._store.write = lambda *args, **kwargs: True
    try:
        for index in range(99):
            api_observability._record(
                "GET", "/api/tasks", 200, 100.0, f"request-{index:08d}"
            )
        api_observability._record(
            "GET", "/api/tasks", 503, 100.0, "request-error-0001"
        )
        slo = api_observability.slo_snapshot()
        assert slo["state"] == "met"
        assert slo["samples"] == 100
        assert slo["availability"] == 0.99
        assert slo["burn_rate"] == 1.0
        assert slo["error_budget_remaining"] == 0.0

        for index in range(6):
            api_observability._record(
                "GET", "/api/tasks", 200, 2501.0, f"request-slow-{index:04d}"
            )
        assert api_observability.slo_snapshot()["state"] == "missed"
        samples = api_observability.slo_snapshot()["samples"]
        api_observability._record(
            "GET", "/api/health", 503, 10_000.0, "request-health-0001"
        )
        api_observability._record(
            "POST", "/api/chat", 503, 10_000.0, "request-chat-000001"
        )
        api_observability._record(
            "GET", "/api/coding/events/stream", 503, 10_000.0, "request-stream-001"
        )
        api_observability._record(
            "OPTIONS", "/api/tasks", 503, 10_000.0, "request-options-01"
        )
        assert api_observability.slo_snapshot()["samples"] == samples
        api_observability._slo_samples.appendleft(
            (
                api_observability.time.time()
                - api_observability._SLO_WINDOW_SECONDS
                - 1,
                503,
                10_000.0,
            )
        )
        assert api_observability.slo_snapshot()["samples"] == samples
    finally:
        api_observability._store.write = original_write


def main() -> int:
    asyncio.run(scenario())
    print("API Observability OK - corrélation, latence, cardinalité et erreurs bornées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
