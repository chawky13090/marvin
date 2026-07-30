"""Routes HTTP du chat agentique, du gateway d'outils et du pont MCP."""

from __future__ import annotations

import json
import sys
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

import chat_turn_runtime
import database as db
import agent_autonomy
from action_replay import IdempotencyMismatchError
import tool_gateway
import tool_runtime
import tools as tool_module
from repositories import tool_approvals
from agent import run_agent
from config import (
    BACKEND_DIR,
    DEFAULT_PERMISSION_LEVEL,
    PERMISSION_EXPERT,
    PERMISSION_SECURE,
    PERMISSION_STANDARD,
)


router = APIRouter(tags=["agent-gateway"])
MAX_CHAT_PAYLOAD_BYTES = 32 * 1024 * 1024
MAX_TOOL_ARGUMENT_BYTES = 2 * 1024 * 1024
IDEMPOTENCY_RESPONSES = {
    200: {
        "description": "Résultat exécuté ou relu depuis le reçu.",
        "headers": {
            "Idempotency-Replayed": {
                "description": "true si le résultat provient d'un reçu terminé.",
                "schema": {"type": "string", "enum": ["true", "false"]},
            }
        },
    },
    409: {
        "description": "La même action est active ou son effet précédent est inconnu."
    },
    422: {
        "description": "Clé UUID invalide ou réutilisée avec un autre payload."
    },
}


def _json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


class ChatRequest(BaseModel):
    messages: list[dict] = Field(min_length=1, max_length=200)
    conversationId: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    requestId: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    afterEvent: int = Field(default=0, ge=0, le=10_000_000)
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9._:/-]+$",
    )
    cortex: dict | None = None
    continuationApprovalId: UUID | None = None

    @model_validator(mode="after")
    def validate_payload_size(self) -> "ChatRequest":
        if _json_size(
            {
                "messages": self.messages,
                "conversationId": self.conversationId,
                "model": self.model,
                "cortex": self.cortex,
                "continuationApprovalId": (
                    str(self.continuationApprovalId)
                    if self.continuationApprovalId
                    else None
                ),
            }
        ) > MAX_CHAT_PAYLOAD_BYTES:
            raise ValueError("La requête de chat dépasse la limite autorisée.")
        return self


class ToolExecuteRequest(BaseModel):
    toolName: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    )
    args: dict = Field(default_factory=dict)
    requestId: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    conversationId: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )

    @model_validator(mode="after")
    def validate_argument_size(self) -> "ToolExecuteRequest":
        if _json_size(self.args) > MAX_TOOL_ARGUMENT_BYTES:
            raise ValueError("Les arguments de l'outil dépassent la limite autorisée.")
        return self


class AutonomyRequest(BaseModel):
    mode: str = Field(pattern=r"^(normal|auto|full)$")
    durationMinutes: int = Field(default=60, ge=5, le=480)


@router.post("/api/chat")
async def chat(request: ChatRequest):
    if request.conversationId and db.get_conversation(request.conversationId) is None:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    internal_continuation = request.continuationApprovalId is not None
    if internal_continuation:
        if not request.conversationId or not request.requestId:
            raise HTTPException(
                status_code=422,
                detail="La continuation exige une conversation et un identifiant de requête.",
            )
        approval = tool_approvals.claim_continuation(
            str(request.continuationApprovalId),
            conversation_id=request.conversationId,
            request_id=request.requestId,
        )
        if approval is None:
            raise HTTPException(
                status_code=409,
                detail="Cette action approuvée a déjà été poursuivie ou ne correspond pas à la conversation.",
            )
    if not request.requestId:

        async def event_stream():
            async for chunk in run_agent(
                request.messages,
                request.conversationId,
                request.model,
                request.cortex,
                internal_continuation=internal_continuation,
            ):
                yield chunk

    else:
        fingerprint = chat_turn_runtime.payload_hash(
            {
                "messages": request.messages,
                "conversationId": request.conversationId,
                "model": request.model,
                "cortex": request.cortex,
                "continuationApprovalId": (
                    str(request.continuationApprovalId)
                    if request.continuationApprovalId
                    else None
                ),
            }
        )

        def producer():
            return run_agent(
                request.messages,
                request.conversationId,
                request.model,
                request.cortex,
                request_id=request.requestId,
                internal_continuation=internal_continuation,
            )

        async def event_stream():
            try:
                async for chunk in chat_turn_runtime.subscribe(
                    request_id=request.requestId,
                    fingerprint=fingerprint,
                    conversation_id=request.conversationId,
                    producer_factory=producer,
                    after_sequence=request.afterEvent,
                ):
                    yield chunk
            except ValueError:
                event = {
                    "type": "error",
                    "message": "Cet identifiant de requête appartient à une autre demande.",
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _current_permission_level() -> int:
    return tool_runtime.current_permission_level(db)


async def _execute_through_gateway(
    request: ToolExecuteRequest,
    *,
    source: str,
    confirmed_by_ui: bool,
    idempotency_key: str | None = None,
) -> tool_gateway.ToolGatewayResult:
    return await tool_runtime.execute(
        request.toolName,
        request.args,
        source=source,
        permission_level=_current_permission_level(),
        conversation_id=request.conversationId,
        request_id=request.requestId,
        confirmed_by_ui=confirmed_by_ui,
        idempotency_key=idempotency_key,
    )


def _tool_outcome_response(outcome: tool_gateway.ToolGatewayResult):
    payload: dict[str, Any] = {"result": outcome.result}
    observation_errors = tuple(getattr(outcome, "observation_errors", ()))
    if observation_errors:
        payload["observability"] = {
            "status": "degraded",
            "errors": list(observation_errors),
        }
    headers: dict[str, str] = {}
    replay = outcome.result.get("_replay") if isinstance(outcome.result, dict) else None
    if isinstance(replay, dict):
        headers["Idempotency-Replayed"] = (
            "true" if replay.get("reused") is True else "false"
        )
        if replay.get("state") in {"in_progress", "unknown"}:
            return JSONResponse(status_code=409, content=payload, headers=headers)
    if outcome.status_code != 200:
        return JSONResponse(
            status_code=outcome.status_code,
            content=payload,
            headers=headers,
        )
    if headers:
        return JSONResponse(content=payload, headers=headers)
    return payload


@router.post("/api/tools", responses=IDEMPOTENCY_RESPONSES)
async def execute_tool_endpoint(
    request: ToolExecuteRequest,
    idempotency_key: Annotated[
        UUID | None,
        Header(alias="Idempotency-Key"),
    ] = None,
):
    try:
        outcome = await _execute_through_gateway(
            request,
            source="ui",
            confirmed_by_ui=False,
            idempotency_key=str(idempotency_key) if idempotency_key else None,
        )
    except IdempotencyMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail="Cette clé d'idempotence appartient à une autre opération.",
        ) from exc
    return _tool_outcome_response(outcome)


@router.get("/api/approvals/{approval_id}")
async def get_tool_approval_endpoint(approval_id: UUID):
    approval = tool_approvals.resolve_status(str(approval_id))
    if approval is None:
        raise HTTPException(status_code=404, detail="Demande d'approbation introuvable.")
    reason = str(approval.get("decision_reason") or "")
    public_status = (
        "superseded"
        if approval.get("status") == "expired" and reason == "superseded"
        else approval.get("status")
    )
    return {
        "approvalId": str(approval_id),
        "status": public_status,
        "active": public_status == "pending",
        "expiresAt": approval.get("expires_at"),
    }


@router.post("/api/approvals/{approval_id}/approve", responses=IDEMPOTENCY_RESPONSES)
async def approve_tool_endpoint(
    approval_id: UUID,
    idempotency_key: Annotated[
        UUID | None,
        Header(alias="Idempotency-Key"),
    ] = None,
):
    approval = tool_approvals.claim(str(approval_id))
    if approval is None:
        raise HTTPException(status_code=404, detail="Demande d'approbation introuvable.")
    if approval["status"] == "expired":
        raise HTTPException(status_code=410, detail="Cette demande d'approbation a expiré.")
    if approval["status"] != "executing" or not approval.get("claimed"):
        raise HTTPException(
            status_code=409,
            detail=f"Cette demande est déjà {approval['status']}.",
        )
    request = ToolExecuteRequest(
        toolName=approval["tool_name"],
        args=approval["arguments"],
        requestId=approval.get("request_id") or None,
        conversationId=approval.get("conversation_id") or None,
    )
    try:
        outcome = await _execute_through_gateway(
            request,
            source="approval_ui",
            confirmed_by_ui=True,
            idempotency_key=str(idempotency_key) if idempotency_key else None,
        )
    except Exception:
        tool_approvals.finish(
            str(approval_id),
            approved=False,
            reason="execution_exception",
        )
        raise
    approved = outcome.executed and outcome.status_code == 200
    tool_approvals.finish(
        str(approval_id),
        approved=approved,
        reason="executed" if approved else f"status_{outcome.status_code}",
    )
    return _tool_outcome_response(outcome)


@router.post("/api/approvals/{approval_id}/deny")
async def deny_tool_endpoint(approval_id: UUID):
    approval = tool_approvals.deny(str(approval_id))
    if approval is None:
        raise HTTPException(status_code=404, detail="Demande d'approbation introuvable.")
    if approval["status"] != "denied":
        raise HTTPException(
            status_code=409,
            detail=f"Cette demande est déjà {approval['status']}.",
        )
    return {"status": "denied", "approvalId": str(approval_id)}


@router.get("/api/autonomy")
async def get_autonomy():
    grant = agent_autonomy.current(db)
    permission_level = _current_permission_level()
    return {
        **grant,
        "permissionLevel": permission_level,
        "permissionLabel": {
            PERMISSION_SECURE: "Sécurisé",
            PERMISSION_STANDARD: "Standard",
            PERMISSION_EXPERT: "Expert",
        }.get(permission_level, "Standard"),
    }


@router.put("/api/autonomy")
async def set_autonomy(request: AutonomyRequest):
    grant = agent_autonomy.configure(
        db,
        request.mode,
        request.durationMinutes,
    )
    permission_level = _current_permission_level()
    return {
        **grant,
        "permissionLevel": permission_level,
        "permissionLabel": {
            PERMISSION_SECURE: "Sécurisé",
            PERMISSION_STANDARD: "Standard",
            PERMISSION_EXPERT: "Expert",
        }.get(permission_level, "Standard"),
    }


@router.get("/api/tools/list")
async def list_tools_endpoint():
    return {
        "tools": tool_module.TOOLS_SPEC,
        "count": len(tool_module.TOOLS_SPEC),
        "registry_synced": len(tool_module.TOOLS_REGISTRY)
        == len(tool_module.TOOLS_SPEC),
        "harness": tool_gateway.coverage_report(
            tool_module.TOOLS_REGISTRY,
            tool_module.TOOLS_SPEC,
        ),
    }


@router.post("/api/mcp/execute", responses=IDEMPOTENCY_RESPONSES)
async def execute_tool_mcp(
    request: ToolExecuteRequest,
    idempotency_key: Annotated[
        UUID | None,
        Header(alias="Idempotency-Key"),
    ] = None,
):
    try:
        outcome = await _execute_through_gateway(
            request,
            source="mcp",
            confirmed_by_ui=False,
            idempotency_key=str(idempotency_key) if idempotency_key else None,
        )
    except IdempotencyMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail="Cette clé d'idempotence appartient à une autre opération.",
        ) from exc
    return _tool_outcome_response(outcome)


@router.get("/api/mcp/config")
async def mcp_config():
    python_executable = sys.executable
    server_script = str((BACKEND_DIR / "mcp_server.py").resolve())
    permission_level = _current_permission_level()
    permission_labels = {
        PERMISSION_SECURE: {
            "label": "Sécurisé",
            "note": "Les outils dangereux sont bloqués pour les appelants MCP.",
        },
        PERMISSION_STANDARD: {
            "label": "Standard",
            "note": (
                "Les outils dangereux renvoient une demande de confirmation; "
                "le client MCP doit rappeler après approbation."
            ),
        },
        PERMISSION_EXPERT: {
            "label": "Expert",
            "note": (
                "Les outils dangereux suivent le contrat Expert, y compris via MCP."
            ),
        },
    }
    config = {
        "mcpServers": {
            "marvin": {
                "command": python_executable,
                "args": [server_script],
            }
        }
    }
    return {
        "python_executable": python_executable,
        "server_script": server_script,
        "permission_level": permission_level,
        "permission_info": permission_labels.get(
            permission_level,
            permission_labels[PERMISSION_STANDARD],
        ),
        "config_json": json.dumps(config, indent=2, ensure_ascii=False),
        "tools_count": len(tool_module.TOOLS_SPEC),
    }
