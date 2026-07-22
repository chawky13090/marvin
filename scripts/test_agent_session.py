"""Regressions de préparation durable d'un tour agentique."""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_session as session


async def _exercise_new_turn() -> None:
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Analyse cette capture"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            "partie mal formée",
        ],
    }]
    background_tasks: set[asyncio.Task] = set()
    title_upgrade = AsyncMock(return_value=None)

    with (
        patch.object(
            session.db,
            "create_conversation",
            return_value={"id": "conversation-new", "title": "Nouvelle conversation"},
        ) as create_conversation,
        patch.object(session.db, "create_message") as create_message,
        patch.object(
            session.db,
            "get_conversation",
            return_value={"id": "conversation-new", "title": "Nouvelle conversation"},
        ),
        patch.object(session.db, "update_conversation_title") as update_title,
        patch.object(
            session,
            "persist_and_analyze_screenshots",
            AsyncMock(return_value=[{"id": "shot-1"}]),
        ),
        patch.object(session, "upgrade_title", title_upgrade),
    ):
        prepared = await session.prepare_turn(
            messages,
            None,
            "request-1",
            background_tasks=background_tasks,
        )
        if background_tasks:
            await asyncio.gather(*tuple(background_tasks))

    assert prepared.conversation_id == "conversation-new"
    assert prepared.user_query == "Analyse cette capture"
    assert prepared.events == [
        {"type": "conv_id", "conversationId": "conversation-new"},
        {"type": "screenshots_saved", "count": 1},
    ]
    create_conversation.assert_called_once_with("Nouvelle conversation")
    create_message.assert_called_once_with(
        "conversation-new",
        "user",
        "Analyse cette capture",
        client_request_id="request-1",
    )
    update_title.assert_called_once()
    title_upgrade.assert_awaited_once_with("conversation-new", "Analyse cette capture")


async def _exercise_existing_turn() -> None:
    with (
        patch.object(session.db, "create_conversation") as create_conversation,
        patch.object(session.db, "create_message") as create_message,
        patch.object(
            session.db,
            "get_conversation",
            return_value={"id": "conversation-1", "title": "Titre existant"},
        ),
        patch.object(session.db, "update_conversation_title") as update_title,
    ):
        prepared = await session.prepare_turn(
            [{"role": "user", "parts": [{"type": "text", "text": "Bonjour"}]}],
            "conversation-1",
            "request-2",
        )
    assert prepared.conversation_id == "conversation-1"
    assert prepared.user_query == "Bonjour"
    assert prepared.events == []
    create_conversation.assert_not_called()
    create_message.assert_called_once_with(
        "conversation-1", "user", "Bonjour", client_request_id="request-2"
    )
    update_title.assert_not_called()


def main() -> int:
    assert session.extract_user_text(None) == ""
    assert session.extract_user_text({"role": "assistant", "content": "x"}) == ""
    assert session.extract_user_text({"role": "user", "content": "texte"}) == "texte"
    asyncio.run(_exercise_new_turn())
    asyncio.run(_exercise_existing_turn())

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_smart_title_upgrade" not in definitions

    import agent

    assert callable(agent._prepare_turn)
    assert callable(agent._smart_title_upgrade)
    print("Agent Session OK - création, message, captures, titre, tâches et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
