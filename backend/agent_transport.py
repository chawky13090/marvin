"""Transport Ollama typé et indépendant de la boucle métier du Runner.

Le module connaît HTTP et le JSONL d'Ollama. Il ne connaît ni les conversations SQLite,
ni les outils Marvin, ni le protocole SSE du frontend.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
import logging
from typing import Any, Literal
import uuid

import httpx


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OllamaChatRequest:
    model: str
    system_prompt: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    options: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            # Redondance défensive : certaines versions/clouds ignorent ce champ, mais le
            # message system est déjà présent dans messages[].
            "system": self.system_prompt,
            "messages": self.messages,
            "stream": True,
            "options": self.options,
            "keep_alive": "30m",
        }
        if self.tools is not None:
            payload["tools"] = self.tools
        return payload


@dataclass(frozen=True, slots=True)
class OllamaStreamEvent:
    kind: Literal["text", "thinking", "tool_calls", "done"]
    text: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()


class OllamaHTTPError(RuntimeError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"Ollama HTTP {status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body[:200]


def create_client(*, read_timeout: float = 300.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=10.0)
    )


def decode_stream_line(line: str) -> tuple[OllamaStreamEvent, ...]:
    """Décode une ligne JSONL Ollama; une ligne partielle/invalide est ignorée."""
    if not line:
        return ()
    try:
        chunk = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(chunk, dict):
        return ()

    events: list[OllamaStreamEvent] = []
    message = chunk.get("message")
    if isinstance(message, dict):
        thinking = message.get("thinking")
        if isinstance(thinking, str) and thinking:
            events.append(OllamaStreamEvent("thinking", text=thinking))
        content = message.get("content")
        if isinstance(content, str) and content:
            events.append(OllamaStreamEvent("text", text=content))
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            valid_calls = tuple(call for call in calls if isinstance(call, dict))
            if valid_calls:
                events.append(OllamaStreamEvent("tool_calls", tool_calls=valid_calls))
    if chunk.get("done") is True:
        events.append(OllamaStreamEvent("done"))
    return tuple(events)


async def stream_chat(
    client: httpx.AsyncClient,
    base_url: str,
    request: OllamaChatRequest,
) -> AsyncIterator[OllamaStreamEvent]:
    """Émet les événements décodés d'un unique appel `/api/chat`."""
    async with client.stream(
        "POST",
        f"{base_url.rstrip('/')}/api/chat",
        json=request.payload(),
    ) as response:
        if response.status_code != 200:
            body = (await response.aread()).decode(errors="replace")
            raise OllamaHTTPError(response.status_code, body)
        async for line in response.aiter_lines():
            for event in decode_stream_line(line):
                if event.kind == "done":
                    return
                yield event


def error_event(exc: Exception, *, model: str, base_url: str, read_timeout: int) -> dict[str, Any]:
    """Projette une erreur transport publique sans détail interne ni contenu distant."""
    incident = uuid.uuid4().hex
    context = {
        "error_type": type(exc).__name__,
        "incident": incident,
    }
    if isinstance(exc, OllamaHTTPError):
        context["status_code"] = exc.status_code
        message = f"Ollama a refusé la requête (HTTP {exc.status_code})."
    elif isinstance(exc, httpx.ConnectError):
        message = "Impossible de contacter Ollama. Vérifiez son état puis relancez Marvin."
    elif isinstance(exc, httpx.ReadTimeout):
        timeout = max(1, min(int(read_timeout), 3600))
        context["read_timeout"] = timeout
        message = f"Ollama n'a pas répondu avant le délai de {timeout} secondes."
    elif isinstance(exc, httpx.RemoteProtocolError):
        message = "La connexion avec Ollama a été interrompue avant la fin de la réponse."
    else:
        message = "Le transport Ollama a rencontré une erreur interne."

    _LOGGER.warning(
        "ollama_transport_failure error_type=%s incident=%s status_code=%s",
        context["error_type"],
        incident,
        context.get("status_code", "-"),
    )
    return {
        "type": "error",
        "message": f"{message} Incident : {incident}.",
        "incident": incident,
    }
