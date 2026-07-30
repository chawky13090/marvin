"""Contrats des routes chat, outils et MCP extraites de main.py."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import agent_gateway


async def _collect_stream(response) -> str:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
    return b"".join(chunks).decode("utf-8")


async def _exercise_routes() -> None:
    async def generated():
        yield 'data: {"type":"done"}\n\n'

    with patch.object(agent_gateway, "run_agent", return_value=generated()):
        response = await agent_gateway.chat(
            agent_gateway.ChatRequest(messages=[{"role": "user", "content": "bonjour"}])
        )
        body = await _collect_stream(response)
    assert '"type":"done"' in body
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    with patch.object(agent_gateway.db, "get_conversation", return_value=None):
        try:
            await agent_gateway.chat(
                agent_gateway.ChatRequest(
                    messages=[{"role": "user", "content": "bonjour"}],
                    conversationId="conversation-absente",
                )
            )
        except agent_gateway.HTTPException as exc:
            assert exc.status_code == 404
            assert exc.detail == "Conversation introuvable."
        else:
            raise AssertionError("Une conversation inconnue doit être refusée avant le SSE.")

    approval_id = agent_gateway.UUID("39d97c47-bf56-4f28-a6cb-bcc6f0102190")
    with patch.object(
        agent_gateway.tool_approvals,
        "resolve_status",
        return_value={
            "id": str(approval_id),
            "status": "expired",
            "decision_reason": "superseded",
            "expires_at": 123.0,
        },
    ):
        approval_status = await agent_gateway.get_tool_approval_endpoint(approval_id)
    assert approval_status == {
        "approvalId": str(approval_id),
        "status": "superseded",
        "active": False,
        "expiresAt": 123.0,
    }

    async def continuation_subscription(**kwargs):
        async for item in kwargs["producer_factory"]():
            yield item

    with (
        patch.object(
            agent_gateway.db,
            "get_conversation",
            return_value={"id": "conversation-1"},
        ),
        patch.object(
            agent_gateway.tool_approvals,
            "claim_continuation",
            return_value={"id": str(approval_id), "status": "approved"},
        ) as claim_continuation,
        patch.object(agent_gateway, "run_agent", return_value=generated()) as run_agent,
        patch.object(
            agent_gateway.chat_turn_runtime,
            "subscribe",
            continuation_subscription,
        ),
    ):
        response = await agent_gateway.chat(
            agent_gateway.ChatRequest(
                messages=[{"role": "user", "content": "Poursuis"}],
                conversationId="conversation-1",
                requestId="continuation-1",
                continuationApprovalId=approval_id,
            )
        )
        body = await _collect_stream(response)
    assert '"type":"done"' in body
    claim_continuation.assert_called_once_with(
        str(approval_id),
        conversation_id="conversation-1",
        request_id="continuation-1",
    )
    assert run_agent.call_args.kwargs["internal_continuation"] is True

    with (
        patch.object(
            agent_gateway.db,
            "get_conversation",
            return_value={"id": "conversation-1"},
        ),
        patch.object(
            agent_gateway.tool_approvals,
            "claim_continuation",
            return_value=None,
        ),
    ):
        try:
            await agent_gateway.chat(
                agent_gateway.ChatRequest(
                    messages=[{"role": "user", "content": "Poursuis"}],
                    conversationId="conversation-1",
                    requestId="continuation-2",
                    continuationApprovalId=approval_id,
                )
            )
        except agent_gateway.HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Une approbation déjà consommée doit être refusée.")

    async def rejected_subscription(**_kwargs):
        raise ValueError("secret interne qui ne doit pas sortir")
        yield ""

    with patch.object(
        agent_gateway.chat_turn_runtime,
        "subscribe",
        rejected_subscription,
    ):
        response = await agent_gateway.chat(
            agent_gateway.ChatRequest(
                messages=[{"role": "user", "content": "bonjour"}],
                requestId="request-1",
            )
        )
        body = await _collect_stream(response)
    assert "secret interne" not in body
    assert "autre demande" in body

    outcome = SimpleNamespace(
        status_code=200,
        result={"success": True},
        observation_errors=(),
    )
    with patch.object(
        agent_gateway,
        "_execute_through_gateway",
        AsyncMock(return_value=outcome),
    ) as execute:
        response = await agent_gateway.execute_tool_endpoint(
            agent_gateway.ToolExecuteRequest(toolName="date_now")
        )
    assert response == {"result": {"success": True}}
    assert execute.await_args.kwargs == {
        "source": "ui",
        "confirmed_by_ui": False,
        "idempotency_key": None,
    }

    degraded = SimpleNamespace(
        status_code=200,
        result={"success": True},
        observation_errors=("audit:OSError",),
    )
    with patch.object(
        agent_gateway,
        "_execute_through_gateway",
        AsyncMock(return_value=degraded),
    ):
        response = await agent_gateway.execute_tool_endpoint(
            agent_gateway.ToolExecuteRequest(toolName="date_now")
        )
    assert response["observability"] == {
        "status": "degraded",
        "errors": ["audit:OSError"],
    }

    refused = SimpleNamespace(
        status_code=403,
        result={"error": "Permission refusée", "permission_denied": True},
        observation_errors=(),
    )
    with patch.object(
        agent_gateway,
        "_execute_through_gateway",
        AsyncMock(return_value=refused),
    ):
        response = await agent_gateway.execute_tool_endpoint(
            agent_gateway.ToolExecuteRequest(toolName="date_now")
        )
    assert response.status_code == 403
    assert json.loads(response.body)["result"]["permission_denied"] is True

    replayed = SimpleNamespace(
        status_code=200,
        result={
            "success": True,
            "_replay": {"state": "completed", "reused": True},
        },
        observation_errors=(),
    )
    key = agent_gateway.UUID("d48cccf9-2c8b-4be9-94a8-6d6fcb930f10")
    with patch.object(
        agent_gateway,
        "_execute_through_gateway",
        AsyncMock(return_value=replayed),
    ) as execute:
        response = await agent_gateway.execute_tool_endpoint(
            agent_gateway.ToolExecuteRequest(toolName="task_create"),
            idempotency_key=key,
        )
    assert response.headers["idempotency-replayed"] == "true"
    assert execute.await_args.kwargs["idempotency_key"] == str(key)

    concurrent = SimpleNamespace(
        status_code=200,
        result={
            "success": False,
            "_replay": {"state": "in_progress", "reused": False},
        },
        observation_errors=(),
    )
    with patch.object(
        agent_gateway,
        "_execute_through_gateway",
        AsyncMock(return_value=concurrent),
    ):
        response = await agent_gateway.execute_tool_endpoint(
            agent_gateway.ToolExecuteRequest(toolName="task_create"),
            idempotency_key=key,
        )
    assert response.status_code == 409

    with patch.object(
        agent_gateway,
        "_execute_through_gateway",
        AsyncMock(side_effect=agent_gateway.IdempotencyMismatchError("mismatch")),
    ):
        try:
            await agent_gateway.execute_tool_endpoint(
                agent_gateway.ToolExecuteRequest(toolName="task_create"),
                idempotency_key=key,
            )
        except agent_gateway.HTTPException as exc:
            assert exc.status_code == 422
            assert "mismatch" not in str(exc.detail)
        else:
            raise AssertionError("Le conflit de fingerprint doit produire HTTP 422.")


def _expect_invalid(factory) -> None:
    try:
        factory()
    except ValidationError:
        return
    raise AssertionError("La charge invalide aurait dû être refusée.")


def main() -> int:
    _expect_invalid(lambda: agent_gateway.ChatRequest(messages=[]))
    _expect_invalid(
        lambda: agent_gateway.ChatRequest(
            messages=[{"role": "user", "content": "x"}],
            conversationId="../escape",
        )
    )
    _expect_invalid(
        lambda: agent_gateway.ToolExecuteRequest(toolName="../powershell", args={})
    )
    with patch.object(agent_gateway, "MAX_CHAT_PAYLOAD_BYTES", 100):
        _expect_invalid(
            lambda: agent_gateway.ChatRequest(
                messages=[{"role": "user", "content": "x" * 200}]
            )
        )
    with (
        patch.object(agent_gateway.db, "get_setting", return_value=99),
    ):
        assert (
            agent_gateway._current_permission_level()
            == agent_gateway.DEFAULT_PERMISSION_LEVEL
        )
    with patch.object(
        agent_gateway.db,
        "get_setting",
        side_effect=RuntimeError("base indisponible"),
    ):
        assert (
            agent_gateway._current_permission_level()
            == agent_gateway.DEFAULT_PERMISSION_LEVEL
        )

    config = asyncio.run(agent_gateway.mcp_config())
    parsed = json.loads(config["config_json"])
    assert parsed["mcpServers"]["marvin"]["command"] == sys.executable
    assert Path(config["server_script"]).name == "mcp_server.py"
    assert "C:\\Users\\Chawb" not in config["config_json"]

    asyncio.run(_exercise_routes())

    main_source = (BACKEND / "main.py").read_text(encoding="utf-8-sig")
    agent_source = (BACKEND / "agent.py").read_text(encoding="utf-8-sig")
    assert "app.include_router(agent_gateway_router)" in main_source
    assert "class ChatRequest" not in main_source
    assert "class ToolExecuteRequest" not in main_source
    assert 'content={"detail": f"Erreur interne : {exc}"}' not in main_source
    assert '"incident_id": incident_id' in main_source
    assert 'source="agent_chat"' in agent_source
    assert "execute_registered_tool=_execute_agent_tool" in agent_source
    assert "execute_registered_tool=_execute_registered_tool" not in agent_source

    routes = {
        route.path
        for route in agent_gateway.router.routes
    }
    assert routes == {
        "/api/chat",
        "/api/tools",
        "/api/approvals/{approval_id}",
        "/api/approvals/{approval_id}/approve",
        "/api/approvals/{approval_id}/deny",
        "/api/autonomy",
        "/api/tools/list",
        "/api/mcp/execute",
        "/api/mcp/config",
    }
    print("Agent Gateway API OK - extraction, bornes, SSE, outils, MCP et erreurs expurgées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
