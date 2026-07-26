"""Synthèse terminale lorsque le Runner atteint son budget."""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable


async def synthesize_budget_answer(
    *,
    stop_reason: str,
    active_model: str,
    system_prompt: str,
    ollama_messages: list[dict[str, Any]],
    options: dict[str, Any],
    base_url: str,
    request_factory: Callable[..., Any],
    client_factory: Callable[..., Any],
    stream_chat: Callable[..., AsyncIterator[Any]],
) -> AsyncIterator[dict[str, str]]:
    """Effectue un dernier appel sans outil et garantit une réponse utilisateur."""
    messages = list(ollama_messages)
    messages.append({
        "role": "user",
        "content": (
            f"⛔ Tu as atteint le budget ({stop_reason}) pour ce tour. Tu ne peux "
            "PLUS utiliser aucun outil. Réponds MAINTENANT, en français, avec une "
            "synthèse aussi complète que possible de ce que tu as déjà trouvé pour "
            "répondre à la demande initiale de l'utilisateur. Si des informations "
            "manquent encore, dis-le clairement plutôt que de rester silencieux."
        ),
    })
    content = ""
    try:
        async with client_factory(read_timeout=120.0) as client:
            request = request_factory(
                model=active_model,
                system_prompt=system_prompt,
                messages=messages,
                tools=None,
                options=options,
            )
            async for event in stream_chat(client, base_url, request):
                if event.kind == "text":
                    content += event.text
                    yield {"type": "text", "text": event.text}
    except Exception:
        pass

    if not content.strip():
        content = (
            "Je n'ai pas réussi à conclure cette recherche dans le nombre d'étapes "
            "autorisées. Les résultats déjà produits restent disponibles ; demande-moi "
            "de continuer pour reprendre sans annoncer un succès non vérifié."
        )
        yield {"type": "text", "text": content}
    yield {"type": "_budget_answer", "content": content}
