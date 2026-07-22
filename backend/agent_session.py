"""Préparation durable d'un tour de conversation Marvin.

Cette frontière possède le cycle de vie de la session courante : création de conversation,
persistance idempotente du message utilisateur, captures et titre. Elle ne sélectionne ni
modèle, ni outil, ni stratégie d'orchestration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import database as db
import tools
from agent_context import persist_and_analyze_screenshots
from agent_policy import autotitle_from_text


@dataclass(slots=True)
class PreparedTurn:
    conversation_id: str
    user_query: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)


def extract_user_text(message: dict[str, Any] | None) -> str:
    """Extrait uniquement le texte utilisateur des formats UI historiques."""
    if not message or message.get("role") != "user":
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    parts = message.get("parts")
    if isinstance(parts, list):
        return "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


async def upgrade_title(conversation_id: str, user_text: str) -> None:
    """Améliore le titre en arrière-plan sans bloquer ni casser le tour."""
    try:
        prompt = (
            "Résume cette demande en un titre TRÈS court (3 à 5 mots), en français, sans "
            "guillemets ni point final, comme un titre d'onglet de navigateur. Réponds "
            "UNIQUEMENT le titre, rien d'autre.\n\nDemande : "
            + user_text[:500]
        )
        raw = await tools._ollama_generate(prompt, timeout=25)
        title = (raw or "").strip().strip('"“”«»').split("\n")[0].strip(" .")[:60]
        if title:
            db.upgrade_conversation_title_silent(conversation_id, title)
    except Exception:
        pass


async def prepare_turn(
    messages: list[dict[str, Any]],
    conversation_id: str | None,
    request_id: str | None,
    *,
    background_tasks: set[asyncio.Task] | None = None,
) -> PreparedTurn:
    """Crée/reprend une session et persiste son entrée avant l'orchestration LLM."""
    events: list[dict[str, Any]] = []
    if not conversation_id:
        conversation = db.create_conversation("Nouvelle conversation")
        conversation_id = conversation["id"]
        events.append({"type": "conv_id", "conversationId": conversation_id})

    last_message = messages[-1] if messages else None
    user_query = extract_user_text(last_message)
    if not last_message or last_message.get("role") != "user":
        return PreparedTurn(conversation_id=conversation_id, events=events)

    db.create_message(
        conversation_id,
        "user",
        user_query,
        client_request_id=request_id,
    )

    content = last_message.get("content")
    if isinstance(content, list):
        try:
            screenshots = await persist_and_analyze_screenshots(conversation_id, content)
            if screenshots:
                events.append({"type": "screenshots_saved", "count": len(screenshots)})
        except Exception:
            pass

    try:
        conversation = db.get_conversation(conversation_id)
        if (
            conversation
            and conversation.get("title") == "Nouvelle conversation"
            and user_query.strip()
        ):
            db.update_conversation_title(conversation_id, autotitle_from_text(user_query))
            task = asyncio.create_task(upgrade_title(conversation_id, user_query))
            if background_tasks is not None:
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
    except Exception:
        pass

    return PreparedTurn(
        conversation_id=conversation_id,
        user_query=user_query,
        events=events,
    )
