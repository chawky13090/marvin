"""Routes de consultation et de gestion des conversations Marvin."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database as db
import chat_turn_runtime


router = APIRouter(tags=["conversations"])


@router.get("/api/conversations")
async def list_conversations(limit: int = 50, offset: int = 0, archived: bool = False):
    return db.list_conversations(limit, offset, archived)


@router.get("/api/conversations/search")
async def search_conversations_endpoint(q: str, limit: int = 50):
    """Recherche full-text dans les titres et les messages.

    Cette route doit rester déclarée avant ``/{cid}``, sinon FastAPI interprète
    littéralement ``search`` comme un identifiant de conversation.
    """
    if not q.strip():
        return []
    return db.search_conversations(q, limit)


@router.get("/api/conversations/{cid}")
async def get_conversation(cid: str):
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation introuvable")
    messages_raw = db.get_messages_by_conversation(cid)

    formatted = []
    for msg in messages_raw:
        if msg["role"] == "tool":
            last_asst = next((m for m in reversed(formatted) if m["role"] == "assistant"), None)
            if last_asst:
                try:
                    results = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
                    if isinstance(results, list):
                        for result in results:
                            for invocation in last_asst.get("toolInvocations", []):
                                if invocation.get("toolCallId") == result.get("toolCallId"):
                                    invocation["state"] = "result"
                                    invocation["result"] = result.get("result")
                                    invocation["evidence"] = result.get("evidence")
                            for part in last_asst.get("parts", []):
                                if (
                                    part.get("type") == "tool-invocation"
                                    and part.get("toolInvocation", {}).get("toolCallId")
                                    == result.get("toolCallId")
                                ):
                                    part["toolInvocation"]["state"] = "result"
                                    part["toolInvocation"]["result"] = result.get("result")
                                    part["toolInvocation"]["evidence"] = result.get("evidence")
                except Exception:
                    pass
            continue

        parts: list = []
        if msg.get("content"):
            parts.append({"type": "text", "text": msg["content"]})

        invocations = []
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tool_call in msg["tool_calls"]:
                invocation = {
                    "state": "call",
                    "toolCallId": tool_call.get("toolCallId", ""),
                    "toolName": tool_call.get("toolName", ""),
                    "args": tool_call.get("args", {}),
                }
                parts.append({"type": "tool-invocation", "toolInvocation": invocation})
                invocations.append(invocation)

        formatted.append(
            {
                "id": msg["id"],
                "role": msg["role"],
                "content": msg.get("content", ""),
                "parts": parts,
                "toolInvocations": invocations,
            }
        )

    incomplete = chat_turn_runtime.incomplete_tool_calls(cid)
    if incomplete:
        for message in formatted:
            if message.get("role") != "assistant":
                continue
            for invocation in message.get("toolInvocations", []):
                state = incomplete.get(invocation.get("toolCallId", ""))
                if state and invocation.get("state") == "call":
                    invocation.update(state)
            for part in message.get("parts", []):
                invocation = part.get("toolInvocation") if isinstance(part, dict) else None
                state = incomplete.get(
                    invocation.get("toolCallId", "")
                    if isinstance(invocation, dict)
                    else ""
                )
                if state and invocation.get("state") == "call":
                    invocation.update(state)

    return {"conversation": conv, "messages": formatted}


@router.delete("/api/conversations/{cid}")
async def delete_conversation(cid: str):
    db.delete_conversation(cid)
    return {"success": True}


class ConversationUpdate(BaseModel):
    title: str | None = None
    projectId: str | None = None
    pinned: bool | None = None
    archived: bool | None = None


@router.put("/api/conversations/{cid}")
async def update_conversation(cid: str, body: ConversationUpdate):
    fields = body.model_dump(exclude_unset=True)
    if "title" in fields and fields["title"] is not None:
        db.update_conversation_title(cid, fields["title"])
    if "projectId" in fields:
        db.update_conversation_project(cid, fields["projectId"])
    if "pinned" in fields and fields["pinned"] is not None:
        db.set_conversation_pinned(cid, fields["pinned"])
    if "archived" in fields and fields["archived"] is not None:
        updated = db.set_conversation_archived(cid, fields["archived"])
        if updated is None:
            raise HTTPException(status_code=404, detail="Conversation introuvable")
    return {"success": True}
