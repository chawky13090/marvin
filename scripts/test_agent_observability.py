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
    )
    route = AsyncMock(return_value=None)
    with (
        patch.object(observability.audit, "log_action") as audit,
        patch.object(observability.db, "log_execution") as execution,
        patch.object(observability.mission_os, "record_action") as proof,
        patch.object(observability.tool_router, "record_success", route),
    ):
        await observability.record_tool_observation(observation)
    audit.assert_called_once_with(
        "net_ping", {"host": "127.0.0.1"}, {"success": True}, source="chat"
    )
    execution.assert_called_once_with(
        "net_ping", {"host": "127.0.0.1"}, {"success": True}, 42,
        conversation_id="conversation-1",
    )
    proof.assert_called_once()
    route.assert_awaited_once_with("teste le serveur", "net_ping")

    # Une destination en panne ne bloque ni les suivantes ni le tour.
    route = AsyncMock(return_value=None)
    with (
        patch.object(observability.audit, "log_action", side_effect=RuntimeError("audit HS")),
        patch.object(observability.db, "log_execution") as execution,
        patch.object(observability.mission_os, "record_action") as proof,
        patch.object(observability.tool_router, "record_success", route),
    ):
        await observability.record_tool_observation(observation)
    execution.assert_called_once()
    proof.assert_called_once()
    route.assert_awaited_once()

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

    import agent
    assert callable(agent._record_tool_observation)
    print("Agent Observability OK - audit, SQLite, preuves, apprentissage et isolation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
