"""Régressions déterministes de la preuve de contexte Ollama."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import ollama_context_runtime as runtime


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, *, loaded: list[dict[str, Any]], shows: dict[str, dict[str, Any]]) -> None:
        self.loaded = loaded
        self.shows = shows

    async def get(self, url: str) -> FakeResponse:
        if url.endswith("/api/version"):
            return FakeResponse({"version": "test"})
        if url.endswith("/api/ps"):
            return FakeResponse({"models": self.loaded})
        return FakeResponse({}, 404)

    async def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
        if not url.endswith("/api/show"):
            return FakeResponse({}, 404)
        payload = self.shows.get(str(json.get("model") or ""))
        return FakeResponse(payload or {}, 200 if payload is not None else 404)


def show(context: int) -> dict[str, Any]:
    return {"model_info": {"test.context_length": context}}


async def main() -> int:
    local_verified = await runtime.inspect_context_runtime(
        ["qwen:4b"],
        client=FakeClient(
            loaded=[{
                "name": "qwen:4b", "context_length": 32_768, "digest": "abc",
                "size": 7_000_000_000, "size_vram": 3_000_000_000,
            }],
            shows={"qwen:4b": show(131_072)},
        ),
    )
    assert local_verified["status"] == "verified"
    assert local_verified["models"][0]["evidence"] == "api_ps_allocated_context"
    assert local_verified["models"][0]["effective_context_tokens"] == 32_768
    assert local_verified["models"][0]["runtime_size_bytes"] == 7_000_000_000
    assert local_verified["models"][0]["runtime_size_vram_bytes"] == 3_000_000_000
    assert local_verified["models"][0]["gpu_residency_ratio"] == 0.4286
    assert local_verified["models"][0]["gpu_residency_scope"] == (
        "ollama_reported_loaded_size_not_guaranteed_full_kv_reservation"
    )

    local_deferred = await runtime.inspect_context_runtime(
        ["qwen:4b"],
        client=FakeClient(loaded=[], shows={"qwen:4b": show(131_072)}),
    )
    assert local_deferred["status"] == "deferred"
    assert local_deferred["models"][0]["effective_context_tokens"] is None
    assert local_deferred["models"][0]["max_context_tokens"] == 131_072

    local_failed = await runtime.inspect_context_runtime(
        ["qwen:4b"],
        client=FakeClient(
            loaded=[{"name": "qwen:4b", "context_length": 4_096}],
            shows={"qwen:4b": show(131_072)},
        ),
    )
    assert local_failed["status"] == "failed"
    assert local_failed["models"][0]["meets_minimum"] is False

    cloud_declared = await runtime.inspect_context_runtime(
        ["qwen:397b-cloud"],
        client=FakeClient(loaded=[], shows={"qwen:397b-cloud": show(262_144)}),
    )
    assert cloud_declared["status"] == "provider_declared"
    assert cloud_declared["models"][0]["provider"] == "cloud"
    assert cloud_declared["models"][0]["evidence"] == "cloud_provider_declared_max"
    assert cloud_declared["models"][0]["effective_context_tokens"] is None
    assert cloud_declared["models"][0]["meets_recommended"] is False
    assert cloud_declared["models"][0]["cloud_provider_declared_max"] == 262_144

    invalid = await runtime.inspect_context_runtime(
        ["bad:cloud"],
        client=FakeClient(loaded=[], shows={}),
    )
    assert invalid["status"] == "failed"
    assert invalid["models"][0]["evidence"] == "show_failed"

    previous = os.environ.get("OLLAMA_CONTEXT_LENGTH")
    try:
        os.environ["OLLAMA_CONTEXT_LENGTH"] = "32768"
        requested_only = await runtime.inspect_context_runtime(
            ["qwen:4b"],
            client=FakeClient(loaded=[], shows={"qwen:4b": show(131_072)}),
        )
        assert requested_only["capture_process_env_tokens"] == 32_768
        assert requested_only["capture_process_env_scope"] == "capture_process_only_not_ollama_runtime"
        assert requested_only["status"] == "deferred", (
            "La configuration du lanceur ne doit jamais devenir une preuve runtime."
        )
    finally:
        if previous is None:
            os.environ.pop("OLLAMA_CONTEXT_LENGTH", None)
        else:
            os.environ["OLLAMA_CONTEXT_LENGTH"] = previous

    print("Ollama context runtime OK - capacité, allocation et défaut séparés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
