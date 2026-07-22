"""Regressions des recus idempotents pour les actions du chat."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import action_replay
from db_connection import db
from db_migrations import MIGRATIONS, apply_migrations


def _initialize(path: Path) -> None:
    with db(path) as connection:
        apply_migrations(connection, MIGRATIONS)


async def _exercise(path: Path) -> None:
    calls = 0

    async def create_once():
        nonlocal calls
        calls += 1
        return {"success": True, "id": "task-1", "access_token": "secret-value"}

    scope = lambda: db(path)
    with patch.object(action_replay, "db", scope):
        first = await action_replay.execute_once(
            request_id="request-1", conversation_id="conversation-1",
            tool_name="task_create", arguments={"title": "Unique"}, operation=create_once,
        )
        second = await action_replay.execute_once(
            request_id="request-1", conversation_id="conversation-1",
            tool_name="task_create", arguments={"title": "Unique"}, operation=create_once,
        )
        assert calls == 1
        assert first["_replay"]["reused"] is False
        assert second["_replay"]["reused"] is True
        assert second["access_token"] == "[MASQUE]"

        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_send():
            entered.set()
            await release.wait()
            return {"success": True, "message_id": "mail-1"}

        running = asyncio.create_task(action_replay.execute_once(
            request_id="request-2", conversation_id="conversation-1",
            tool_name="email_send", arguments={"to": "test@example.invalid"}, operation=slow_send,
        ))
        await entered.wait()
        duplicate = await action_replay.execute_once(
            request_id="request-2", conversation_id="conversation-1",
            tool_name="email_send", arguments={"to": "test@example.invalid"}, operation=slow_send,
        )
        assert duplicate["action_in_progress"] is True
        release.set()
        assert (await running)["success"] is True

        key, args_hash = action_replay.idempotency_key(
            "request-3", "conversation-1", "event_create", {"title": "RDV"}
        )
        with db(path) as connection:
            connection.execute(
                """INSERT INTO action_receipts
                   (idempotency_key, request_id, conversation_id, tool_name, args_hash, status, owner_token)
                   VALUES (?, ?, ?, ?, ?, 'started', 'ancien-processus')""",
                (key, "request-3", "conversation-1", "event_create", args_hash),
            )
        unknown = await action_replay.execute_once(
            request_id="request-3", conversation_id="conversation-1",
            tool_name="event_create", arguments={"title": "RDV"}, operation=create_once,
        )
        assert unknown["action_outcome_unknown"] is True
        assert calls == 1

        unguarded_calls = 0

        async def read_status():
            nonlocal unguarded_calls
            unguarded_calls += 1
            return {"success": True}

        for _ in range(2):
            await action_replay.execute_once(
                request_id="request-4", conversation_id="conversation-1",
                tool_name="task_list", arguments={}, operation=read_status,
            )
        assert unguarded_calls == 2

        with patch.object(action_replay, "complete", side_effect=RuntimeError("disque plein")):
            receipt_failure = await action_replay.execute_once(
                request_id="request-5", conversation_id="conversation-1",
                tool_name="note_create", arguments={"title": "Trace"}, operation=create_once,
            )
        assert receipt_failure["success"] is True
        assert receipt_failure["_replay"]["state"] == "receipt_error"
        assert receipt_failure["_replay"]["receipt_persisted"] is False


def main() -> int:
    assert action_replay.should_guard("email_send")
    assert action_replay.should_guard("task_create")
    assert action_replay.should_guard("pc_run_powershell")
    assert not action_replay.should_guard("task_list")
    assert action_replay.idempotency_key("r", "c", "task_create", {"b": 2, "a": 1}) == (
        action_replay.idempotency_key("r", "c", "task_create", {"a": 1, "b": 2})
    )
    for source in (
        ROOT / "lib" / "contexts" / "ChatContext.jsx",
        ROOT / "lib" / "hooks" / "useSecretary.js",
    ):
        assert "requestId: userMsg.id" in source.read_text(encoding="utf-8-sig")
    main_source = (BACKEND / "main.py").read_text(encoding="utf-8-sig")
    assert "request_id=req.requestId" in main_source

    with tempfile.TemporaryDirectory(prefix="marvin-action-replay-") as directory:
        path = Path(directory) / "receipts.db"
        _initialize(path)
        asyncio.run(_exercise(path))
        with db(path) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    print("Action Replay OK - deduplication, concurrence, interruption et masquage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
