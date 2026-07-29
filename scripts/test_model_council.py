"""Régressions du moteur Council cinq familles, sans appel Ollama réel."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cloud_routing
import database
import model_council
import tools
from config import OLLAMA_URL


class FakeRouting:
    def __init__(self) -> None:
        self.cloud_enabled = True
        self.local_only = False
        self.sensitive = False
        self.ultra = False
        self.models = [f"family-{index}:cloud" for index in range(1, 6)]

    def get_cloud_config(self):
        return self.cloud_enabled, {}

    def is_local_only_lockdown(self):
        return self.local_only

    def is_sensitive_text(self, _text):
        return self.sensitive

    def is_ultra_unrestricted(self):
        return self.ultra

    def get_privacy_preset(self):
        return "ultra" if self.ultra else "normal"

    def detect_task(self, _question):
        return "general"

    def list_distinct_cloud_models(self, _need):
        return list(self.models)

    def model_family(self, model):
        return model.split(":", 1)[0]


async def main() -> None:
    routing = FakeRouting()
    calls: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        prompt = payload["prompt"]
        if "arbitre final" in prompt:
            answer = "Réponse arbitrée"
        elif "contradicteur" in prompt:
            answer = "Critique indépendante"
        else:
            answer = f"Avis indépendant {len(calls)}"
        return httpx.Response(200, json={"response": answer})

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    async def no_sleep(_delay: float) -> None:
        return None

    model_council.configure(
        routing=routing,
        get_setting=lambda _name: 2,
        ollama_url="https://ollama.test",
        client_factory=client_factory,
        sleep=no_sleep,
        id_factory=lambda: "council-test",
    )
    result = await model_council.run(
        {"question": "Décision complexe", "evidence": "Fait vérifié"}
    )
    assert result["success"] is True
    assert result["council_id"] == "council-test"
    assert result["panel_size"] == 5
    assert result["concurrency"] == 2
    assert len(result["models_consulted"]) == 5
    assert len(set(result["families"])) == 5
    assert result["critique"]["phase"] == "cross_critique"
    assert result["arbitration"]["phase"] == "arbitration"
    assert result["answer"] == "Réponse arbitrée"
    assert len(calls) == 7

    routing.sensitive = True
    assert "sensible" in (
        await model_council.run({"question": "Secret"})
    )["error"]
    routing.sensitive = False
    routing.local_only = True
    assert "Hyper local" in (
        await model_council.run({"question": "Question"})
    )["error"]
    routing.local_only = False
    routing.models = routing.models[:4]
    assert "5 familles" in (
        await model_council.run({"question": "Question"})
    )["error"]
    assert "50000" in (
        await model_council.run({"question": "x" * 50_001})
    )["error"]
    assert "12000" in (
        await model_council.run(
            {"question": "Question", "evidence": "x" * 12_001}
        )
    )["error"]

    model_council.configure(
        routing=cloud_routing,
        get_setting=database.get_setting,
        ollama_url=OLLAMA_URL,
    )
    assert tools.execute_ai_model_council is model_council.run
    assert tools.TOOLS_REGISTRY["ai_model_council"] is model_council.run


if __name__ == "__main__":
    asyncio.run(main())
    print("Model Council OK - cinq familles, confidentialité, critique et arbitrage.")
