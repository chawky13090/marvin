"""Routes HTTP du chat agentique, du gateway d'outils et du pont MCP."""

from __future__ import annotations

import json
import sys
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

import audit
import chat_turn_runtime
import database as db
import engineering_runtime
import tool_gateway
import tools as tool_module
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

    @model_validator(mode="after")
    def validate_payload_size(self) -> "ChatRequest":
        if _json_size(
            {
                "messages": self.messages,
                "conversationId": self.conversationId,
                "model": self.model,
                "cortex": self.cortex,
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


@router.post("/api/chat")
async def chat(request: ChatRequest):
    if not request.requestId:

        async def event_stream():
            async for chunk in run_agent(
                request.messages,
                request.conversationId,
                request.model,
                request.cortex,
            ):
                yield chunk

    else:
        fingerprint = chat_turn_runtime.payload_hash(
            {
                "messages": request.messages,
                "conversationId": request.conversationId,
                "model": request.model,
                "cortex": request.cortex,
            }
        )

        def producer():
            return run_agent(
                request.messages,
                request.conversationId,
                request.model,
                request.cortex,
                request_id=request.requestId,
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
    try:
        value = db.get_setting("permission_level")
        candidate = int(value) if value is not None else DEFAULT_PERMISSION_LEVEL
    except Exception:
        # Lecture best-effort d'un réglage : toute panne SQLite doit revenir au
        # défaut autoritaire, jamais interrompre le catalogue ni élargir les droits.
        candidate = DEFAULT_PERMISSION_LEVEL
    if candidate not in {PERMISSION_SECURE, PERMISSION_STANDARD, PERMISSION_EXPERT}:
        return DEFAULT_PERMISSION_LEVEL
    return candidate


async def _execute_through_gateway(
    request: ToolExecuteRequest,
    *,
    source: str,
    confirmed_by_ui: bool,
) -> tool_gateway.ToolGatewayResult:
    return await tool_gateway.execute_tool(
        tool_gateway.ToolGatewayRequest(
            tool_name=request.toolName,
            arguments=request.args,
            source=source,
            permission_level=_current_permission_level(),
            conversation_id=request.conversationId,
            request_id=request.requestId,
            confirmed_by_ui=confirmed_by_ui,
        ),
        registry=tool_module.TOOLS_REGISTRY,
        specifications=tool_module.TOOLS_SPEC,
        database=db,
        normalizer=engineering_runtime.normalize_tool_result,
        audit_logger=audit.log_action,
    )


def _tool_outcome_response(outcome: tool_gateway.ToolGatewayResult):
    payload: dict[str, Any] = {"result": outcome.result}
    observation_errors = tuple(getattr(outcome, "observation_errors", ()))
    if observation_errors:
        payload["observability"] = {
            "status": "degraded",
            "errors": list(observation_errors),
        }
    if outcome.status_code != 200:
        return JSONResponse(status_code=outcome.status_code, content=payload)
    return payload


@router.post("/api/tools")
async def execute_tool_endpoint(request: ToolExecuteRequest):
    outcome = await _execute_through_gateway(
        request,
        source="ui",
        confirmed_by_ui=True,
    )
    return _tool_outcome_response(outcome)


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


@router.post("/api/mcp/execute")
async def execute_tool_mcp(request: ToolExecuteRequest):
    outcome = await _execute_through_gateway(
        request,
        source="mcp",
        confirmed_by_ui=False,
    )
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
