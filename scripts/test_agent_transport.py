"""Régressions déterministes du transport Ollama du Runner."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_transport as transport


def _request(*, tools: list[dict] | None = None) -> transport.OllamaChatRequest:
    return transport.OllamaChatRequest(
        model="model:cloud",
        system_prompt="Règle système",
        messages=[{"role": "system", "content": "Règle système"}],
        tools=tools,
        options={"temperature": 0.1, "top_p": 0.9},
    )


async def _stream(status_code: int = 200) -> tuple[list[transport.OllamaStreamEvent], dict]:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        if status_code != 200:
            return httpx.Response(status_code, text="service indisponible")
        body = "\n".join((
            "ligne invalide",
            json.dumps({"message": {"thinking": "analyse", "content": "Bonjour "}}),
            json.dumps({"message": {"tool_calls": [{"function": {"name": "net_ping"}}]}}),
            json.dumps({"done": True}),
            json.dumps({"message": {"content": "ne doit pas être lu"}}),
        ))
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            event
            async for event in transport.stream_chat(
                client, "http://127.0.0.1:11434/", _request(tools=[{"type": "function"}])
            )
        ]
    return events, captured


async def _run() -> None:
    events, captured = await _stream()
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["payload"]["system"] == "Règle système"
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert captured["payload"]["tools"] == [{"type": "function"}]
    assert captured["payload"]["keep_alive"] == "30m"
    assert [(event.kind, event.text) for event in events[:2]] == [
        ("thinking", "analyse"), ("text", "Bonjour ")
    ]
    assert events[2].kind == "tool_calls"
    assert events[2].tool_calls[0]["function"]["name"] == "net_ping"
    assert all("ne doit pas" not in event.text for event in events)

    try:
        await _stream(status_code=503)
    except transport.OllamaHTTPError as exc:
        assert exc.status_code == 503
        assert "service indisponible" in str(exc)
    else:
        raise AssertionError("Une réponse HTTP non-200 doit lever OllamaHTTPError")


def main() -> int:
    asyncio.run(_run())

    without_tools = _request().payload()
    assert "tools" not in without_tools
    assert transport.decode_stream_line("") == ()
    assert transport.decode_stream_line("pas du JSON") == ()

    connect = transport.error_event(
        httpx.ConnectError("refus"), model="m", base_url="http://ollama", read_timeout=300
    )
    assert connect["type"] == "error" and "start.bat" in connect["message"]
    timeout = transport.error_event(
        httpx.ReadTimeout("lent"), model="m", base_url="http://ollama", read_timeout=120
    )
    assert "120s" in timeout["message"] and "'m'" in timeout["message"]

    import agent
    assert callable(agent._stream_ollama_chat)
    print("Agent Transport OK - payload, JSONL, thinking, outils, arrêt et erreurs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
