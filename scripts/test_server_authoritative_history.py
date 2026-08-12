"""Régressions du transport d'historique serveur TD-015."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from conversation_history import MODEL_HISTORY_MAX_BYTES, UI_HISTORY_MAX_BYTES, model_history, ui_page  # noqa: E402
from api import conversations as api_conversations  # noqa: E402


large_receipt = {
    "toolCallId": "call-large",
    "toolName": "computer_control",
    "result": {"image": "A" * (1024 * 1024), "ok": True},
}
stored = [
    {"id": "u1", "role": "user", "content": "Observe le bureau", "_message_rowid": 1},
    {
        "id": "a1",
        "role": "assistant",
        "content": "",
        "tool_calls": [{"toolCallId": "call-large", "toolName": "computer_control", "args": {"action": "observe"}}],
        "_message_rowid": 2,
    },
    {"id": "t1", "role": "tool", "content": json.dumps([large_receipt]), "tool_results": [large_receipt], "_message_rowid": 3},
]

page = ui_page(stored)
assert page["used_bytes"] <= UI_HISTORY_MAX_BYTES
tool_message = next(item for item in page["messages"] if item["role"] == "tool")
projection = tool_message["tool_results"][0]
assert projection["detail_message_id"] == "t1"
assert projection["result"]["projection_truncated"] is True
assert "A" * 1000 not in json.dumps(projection)

incoming = [{"role": "user", "content": "Que vois-tu maintenant ?"}]
history, metadata = model_history(stored, incoming)
assert history[-1] == incoming[0]
assert metadata["source"] == "sqlite_authoritative"
assert metadata["selected_bytes"] <= MODEL_HISTORY_MAX_BYTES
assert len(json.dumps(history, ensure_ascii=False).encode("utf-8")) <= MODEL_HISTORY_MAX_BYTES


async def verify_detail_binding() -> None:
    original = api_conversations.db.get_message
    try:
        api_conversations.db.get_message = lambda _message_id: {
            "id": "t1",
            "conversation_id": "conv-a",
            "role": "tool",
            "tool_results": [large_receipt],
        }
        detail = await api_conversations.get_tool_result_detail("conv-a", "t1", "call-large")
        assert detail["result"]["ok"] is True
        try:
            await api_conversations.get_tool_result_detail("conv-b", "t1", "call-large")
        except api_conversations.HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("Un reçu ne doit jamais traverser les conversations")
    finally:
        api_conversations.db.get_message = original


asyncio.run(verify_detail_binding())

frontend = (ROOT / "lib" / "contexts" / "ChatContext.jsx").read_text(encoding="utf-8")
assert "conversationIdRef.current ? [userMsg] : allMessages" in frontend
gateway = (BACKEND / "api" / "agent_gateway.py").read_text(encoding="utf-8")
assert "history_context" in gateway and "model_history(stored, incoming)" in gateway

print("Historique serveur autoritatif OK - delta client, budgets, projection et liaison détail.")
