"""Regressions des hooks d'observabilité du Runner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import agent_observability as observability


async def _run() -> None:
    observation = observability.ToolObservation(
        conversation_id="conversation-1",
        user_query="teste le serveur",
        tool_name="net_ping",
        arguments={"host": "127.0.0.1"},
        result={"success": True},
        duration_ms=42,
        request_id="request-12345678",
    )
    route = AsyncMock(return_value=None)
    with (
        patch.object(observability.audit, "log_action") as audit,
        patch.object(observability.db, "log_execution") as execution,
        patch.object(
            observability.mission_os,
            "record_action",
            return_value={"evidence_sequence": 12, "evidence_hash": "a" * 64},
        ) as proof,
        patch.object(observability.tool_router, "record_success", route),
    ):
        receipt = await observability.record_tool_observation(observation)
    audit.assert_called_once_with(
        "net_ping", {"host": "127.0.0.1"}, {"success": True}, source="chat",
        request_id="request-12345678",
    )
    execution.assert_called_once_with(
        "net_ping", {"host": "127.0.0.1"}, {"success": True}, 42,
        conversation_id="conversation-1",
        request_id="request-12345678",
    )
    proof.assert_called_once()
    route.assert_awaited_once_with("teste le serveur", "net_ping")
    assert receipt.evidence_recorded is True
    assert receipt.evidence_sequence == 12 and receipt.evidence_hash == "a" * 64
    assert receipt.public_dict()["status"] == "verified"

    # Une destination en panne ne bloque ni les suivantes ni le tour.
    route = AsyncMock(return_value=None)
    with (
        patch.object(observability.audit, "log_action", side_effect=RuntimeError("audit HS")),
        patch.object(observability.db, "log_execution") as execution,
        patch.object(
            observability.mission_os,
            "record_action",
            return_value={"evidence_sequence": 13, "evidence_hash": "b" * 64},
        ) as proof,
        patch.object(observability.tool_router, "record_success", route),
    ):
        receipt = await observability.record_tool_observation(observation)
    execution.assert_called_once()
    proof.assert_called_once()
    route.assert_awaited_once()
    assert receipt.audit_recorded is False
    assert receipt.evidence_recorded is True
    assert receipt.errors == ("audit:RuntimeError",)

    # Une preuve durable en panne est signalée sans transformer l'action en erreur
    # ni divulguer le message interne de l'exception.
    with (
        patch.object(observability.audit, "log_action"),
        patch.object(observability.db, "log_execution"),
        patch.object(
            observability.mission_os,
            "record_action",
            side_effect=RuntimeError("chemin privé et secret"),
        ),
        patch.object(observability.tool_router, "record_success", AsyncMock()),
    ):
        receipt = await observability.record_tool_observation(observation)
    public = receipt.public_dict()
    assert public["proof_recorded"] is False
    assert public["action_must_not_be_retried"] is True
    assert public["warnings"] == ["evidence:RuntimeError"]
    assert "secret" not in str(public)

    with (
        patch.object(observability.audit, "log_action"),
        patch.object(observability.db, "log_execution"),
        patch.object(observability.mission_os, "record_action", return_value={}),
        patch.object(observability.tool_router, "record_success", AsyncMock()),
    ):
        receipt = await observability.record_tool_observation(observation)
    assert receipt.evidence_recorded is False
    assert "evidence:invalid_receipt" in receipt.errors

    failed = observability.ToolObservation(
        conversation_id="conversation-1", user_query="test", tool_name="net_ping",
        arguments={}, result={"error": "timeout"}, duration_ms=7,
    )
    route = AsyncMock(return_value=None)
    with patch.object(observability.tool_router, "record_success", route):
        await observability.record_tool_observation(failed)
    route.assert_not_awaited()


def main() -> int:
    asyncio.run(_run())
    with patch.object(observability.audit, "log_action") as audit:
        observability.record_long_chain("x" * 300, 9)
    args = audit.call_args.args
    assert args[0] == "_long_tool_chain"
    assert args[1]["count"] == 9 and len(args[1]["query"]) == 200
    with patch.object(observability.bug_log, "log_bug") as log_bug:
        observability.record_empty_model_response(
            conversation_id="conversation-1",
            model="cloud/model",
            required_tool_count=1,
            executed_tool_count=1,
        )
    log_bug.assert_called_once()
    call = log_bug.call_args
    assert call.args[0] == "empty_model_response"
    assert call.kwargs["context"] == {
        "model": "cloud/model",
        "required_tool_count": 1,
        "executed_tool_count": 1,
    }
    assert "query" not in str(call.kwargs)

    import agent
    assert callable(agent._record_tool_observation)
    print("Agent Observability OK - audit, SQLite, preuves, apprentissage et isolation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
