"""Contrats du runtime de génération partagé, sans Ollama réel."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import cloud_routing
import generation_runtime
import tools


class FakeRouting:
    def __init__(self, *, cloud_only: bool = False):
        self.cloud_only = cloud_only

    def resolve_model(self, *_args, **_kwargs):
        return "primary:cloud" if self.cloud_only else "primary:local"

    def is_cloud_only_mode(self):
        return self.cloud_only

    def is_cloud_model(self, model):
        return model.endswith(":cloud")

    def get_privacy_preset(self):
        return "ultra" if self.cloud_only else "normal"

    def detect_task(self, _text):
        return "reasoning"

    def require_cloud_model(self, _need, **_kwargs):
        return "fallback:cloud"


async def main() -> None:
    calls: list[dict] = []
    responses: list[object] = []

    class Response:
        def __init__(self, value):
            self.value = value

        def raise_for_status(self):
            if isinstance(self.value, Exception):
                raise self.value

        def json(self):
            return {"response": self.value}

    class Client:
        is_closed = False

        async def post(self, url, json, timeout):
            calls.append({"url": url, "payload": json, "timeout": timeout.read})
            value = responses.pop(0)
            if isinstance(value, httpx.TimeoutException):
                raise value
            return Response(value)

        async def aclose(self):
            self.is_closed = True

    ticks = iter((0.0, 0.1, 1.0, 1.4, 2.0, 2.5))
    generation_runtime.configure(
        routing=FakeRouting(),
        base_url="http://ollama/",
        model_profiles={"chat": {"model": "fallback:local"}},
        clock=lambda: next(ticks),
        sleep=lambda _seconds: asyncio.sleep(0),
        client_factory=Client,
    )
    generation_runtime.reset_stats()
    with patch("httpx.AsyncClient", Client):
        responses[:] = [" première réponse "]
        first = await generation_runtime.generate("bonjour", return_metadata=True)
        assert first == {
            "text": "première réponse",
            "model": "primary:local",
            "provider": "ollama_local",
            "privacy_preset": "normal",
            "cloud_only": False,
        }

        responses[:] = [
            httpx.ConnectError("temporary"),
            httpx.ConnectError("temporary"),
            "fallback response",
        ]
        fallback = await generation_runtime.generate("analyse")
        assert fallback == "fallback response"

        responses[:] = [httpx.ReadTimeout("slow"), "fast fallback"]
        timeout_fallback = await generation_runtime.generate("analyse lente", timeout=30)
        assert timeout_fallback == "fast fallback"

    assert calls[0]["url"] == "http://ollama/api/generate"
    assert calls[0]["payload"]["stream"] is False
    assert calls[0]["timeout"] == 180
    assert calls[-1]["timeout"] == 30
    assert [call["payload"]["model"] for call in calls] == [
        "primary:local",
        "primary:local",
        "primary:local",
        "fallback:local",
        "primary:local",
        "fallback:local",
    ]
    stats = generation_runtime.snapshot()
    assert stats["total"] == 3
    assert stats["succeeded"] == 3
    assert stats["attempts"] == 6
    assert stats["retries"] == 1
    assert stats["fallbacks"] == 2
    assert "prompt" not in json.dumps(stats).lower()

    try:
        generation_runtime.configure(
            routing=FakeRouting(cloud_only=True),
            base_url="http://ollama",
            model_profiles={},
            client_factory=Client,
        )
    except RuntimeError as exc:
        assert "Fermez le pool" in str(exc)
    else:
        raise AssertionError("Une reconfiguration avec pool ouvert doit être refusée.")
    await generation_runtime.close()

    generation_runtime.configure(
        routing=FakeRouting(cloud_only=True),
        base_url="http://ollama",
        model_profiles={"chat": {"model": "forbidden:local"}},
        sleep=lambda _seconds: asyncio.sleep(0),
        client_factory=Client,
    )
    generation_runtime.reset_stats()
    calls.clear()
    with patch("httpx.AsyncClient", Client):
        responses[:] = [httpx.ReadTimeout("slow"), "cloud fallback"]
        cloud = await generation_runtime.generate("diagnostic", return_metadata=True)
    assert cloud["model"] == "fallback:cloud"
    assert all(call["payload"]["model"].endswith(":cloud") for call in calls)
    await generation_runtime.close()

    for bad_timeout in (0, 901, "invalid"):
        try:
            await generation_runtime.generate("x", timeout=bad_timeout)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Timeout invalide accepté : {bad_timeout!r}")

    generation_runtime.configure(
        routing=cloud_routing,
        base_url=tools.OLLAMA_URL,
        model_profiles=tools.MODEL_PROFILES,
        cloud_only_unavailable=cloud_routing.CloudOnlyModelUnavailable,
    )
    assert tools._ollama_generate is generation_runtime.generate
    assert generation_runtime.snapshot()["total"] == 1
    print(
        "Generation Runtime OK - routage, retry, timeout, repli Cloud, "
        "métriques sans contenu et façade."
    )


if __name__ == "__main__":
    asyncio.run(main())
