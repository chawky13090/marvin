"""Routes de consultation et de gestion des conversations Marvin."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import database as db
import chat_turn_runtime
from conversation_exports import ConversationExportError, export_conversation, _redact
from conversation_history import ui_page
from storage_layout import roots


router = APIRouter(tags=["conversations"])


class ConversationExportRequest(BaseModel):
    format: str = "md"
    mode: str = "lecture"


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


def _build_conversation_response(cid: str, before_rowid: int | None = None) -> JSONResponse:
    """Lit et sérialise une conversation hors de la boucle d'événements.

    ``JSONResponse`` encode immédiatement son contenu en octets. Cette fonction doit donc
    rester synchrone et être appelée par ``asyncio.to_thread`` depuis la route FastAPI.
    """
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation introuvable")
    raw_page = db.get_messages_page(cid, before_rowid=before_rowid, limit=120)
    page = ui_page(raw_page)
    messages_raw = page["messages"]

    formatted = []
    for msg in messages_raw:
        if msg["role"] == "tool":
            last_asst = next((m for m in reversed(formatted) if m["role"] == "assistant"), None)
            if last_asst:
                try:
                    results = msg.get("tool_results")
                    if not isinstance(results, list):
                        results = (
                            json.loads(msg["content"])
                            if isinstance(msg["content"], str)
                            else msg["content"]
                        )
                    if isinstance(results, list):
                        for result in results:
                            for invocation in last_asst.get("toolInvocations", []):
                                if invocation.get("toolCallId") == result.get("toolCallId"):
                                    invocation["state"] = "result"
                                    invocation["result"] = result.get("result")
                                    invocation["evidence"] = result.get("evidence")
                                    if result.get("detail_message_id"):
                                        invocation["detailRef"] = {
                                            "messageId": result["detail_message_id"],
                                            "toolCallId": result.get("toolCallId"),
                                        }
                            for part in last_asst.get("parts", []):
                                if (
                                    part.get("type") == "tool-invocation"
                                    and part.get("toolInvocation", {}).get("toolCallId")
                                    == result.get("toolCallId")
                                ):
                                    part["toolInvocation"]["state"] = "result"
                                    part["toolInvocation"]["result"] = result.get("result")
                                    part["toolInvocation"]["evidence"] = result.get("evidence")
                                    if result.get("detail_message_id"):
                                        part["toolInvocation"]["detailRef"] = {
                                            "messageId": result["detail_message_id"],
                                            "toolCallId": result.get("toolCallId"),
                                        }
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

    next_before_rowid = page["next_before_rowid"]
    has_older_rows = bool(
        next_before_rowid
        and db.has_messages_before(cid, next_before_rowid)
    )
    cutoff_reason = (
        "byte_budget" if page["deferred_messages"] > 0
        else "row_limit" if has_older_rows
        else "none"
    )
    return JSONResponse(content={
        "conversation": conv,
        "messages": formatted,
        "page": {
            "returnedMessages": len(messages_raw),
            "returnedBytes": page["used_bytes"],
            "nextBeforeRowid": next_before_rowid,
            "hasOlderRows": has_older_rows,
            "cutoffReason": cutoff_reason,
            "deferredMessages": page["deferred_messages"],
            "detailsAvailable": page["details_available"],
        },
    })


@router.get("/api/conversations/{cid}")
async def get_conversation(cid: str, before_rowid: int | None = None):
    return await asyncio.to_thread(_build_conversation_response, cid, before_rowid)


def _build_tool_result_detail(
    cid: str, message_id: str, tool_call_id: str
) -> JSONResponse:
    """Lit, masque et sérialise le détail hors de la boucle FastAPI."""
    message = db.get_message(message_id)
    if not message or message.get("conversation_id") != cid or message.get("role") != "tool":
        raise HTTPException(status_code=404, detail="Résultat d'outil introuvable")
    for receipt in message.get("tool_results") or []:
        if isinstance(receipt, dict) and str(receipt.get("toolCallId") or "") == tool_call_id:
            return JSONResponse(content={
                "result": _redact(receipt.get("result")),
                "evidence": _redact(receipt.get("evidence")),
            })
    raise HTTPException(status_code=404, detail="Résultat d'outil introuvable")


@router.get("/api/conversations/{cid}/messages/{message_id}/tool-results/{tool_call_id}")
async def get_tool_result_detail(cid: str, message_id: str, tool_call_id: str):
    """Retourne un reçu masqué, strictement lié à sa conversation et son appel."""
    return await asyncio.to_thread(
        _build_tool_result_detail, cid, message_id, tool_call_id
    )


@router.post("/api/conversations/{cid}/exports")
async def create_conversation_export(cid: str, body: ConversationExportRequest):
    """Produit un artefact serveur portable, sans dependre de l'etat du navigateur."""
    try:
        return await __import__("asyncio").to_thread(
            export_conversation, cid, body.format, body.mode
        )
    except ConversationExportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/conversations/{cid}/exports/download")
async def download_conversation_export(cid: str, path: str):
    candidate = Path(path).expanduser().resolve()
    _, export_root = roots()
    allowed = (export_root / "documents" / "conversations").resolve()
    try:
        candidate.relative_to(allowed)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Export introuvable") from error
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Export introuvable")
    if not candidate.name.startswith(f"{cid}-"):
        raise HTTPException(status_code=404, detail="Export introuvable")
    return FileResponse(candidate, filename=candidate.name)


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
