"""Regressions du journal durable et detachable des tours de chat."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import chat_turn_runtime
from db_connection import db
from db_migrations import MIGRATIONS, apply_migrations


def _event(chunk: str) -> dict:
    line = next(line for line in chunk.splitlines() if line.startswith("data: "))
    return json.loads(line[6:])


async def _exercise(path: Path) -> None:
    scope = lambda: db(path)
    release = asyncio.Event()
    starts = 0

    async def producer():
        nonlocal starts
        starts += 1
        yield 'data: {"type":"text","text":"debut"}\n\n'
        await release.wait()
        yield 'data: {"type":"text","text":" fin"}\n\n'
        yield 'data: {"type":"done"}\n\n'

    fingerprint = chat_turn_runtime.payload_hash({"messages": [{"role": "user", "content": "test"}]})
    with patch.object(chat_turn_runtime, "db", scope):
        try:
            chat_turn_runtime._append_event(
                "parent-absent",
                {"type": "done"},
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("Un événement sans tour parent doit être refusé.")
        with db(path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM chat_turn_events WHERE request_id = 'parent-absent'"
            ).fetchone()[0] == 0

        first_stream = chat_turn_runtime.subscribe(
            request_id="turn-1", fingerprint=fingerprint, conversation_id="conv-1",
            producer_factory=producer,
        )
        first = await anext(first_stream)
        assert _event(first)["text"] == "debut"
        await first_stream.aclose()  # simule un navigateur qui quitte la page
        assert starts == 1

        release.set()
        await asyncio.sleep(0.15)
        replayed = []
        async for chunk in chat_turn_runtime.subscribe(
            request_id="turn-1", fingerprint=fingerprint, conversation_id="conv-1",
            producer_factory=producer, after_sequence=1,
        ):
            replayed.append(_event(chunk))
        assert starts == 1, "Une reconnexion ne doit pas relancer le LLM."
        assert [item["type"] for item in replayed] == ["text", "done"]
        assert [item["turnSeq"] for item in replayed] == [2, 3]

        mismatch = chat_turn_runtime.subscribe(
            request_id="turn-1", fingerprint="autre", conversation_id="conv-1",
            producer_factory=producer,
        )
        try:
            await anext(mismatch)
        except ValueError:
            pass
        else:
            raise AssertionError("Un requestId reutilise avec un payload divergent doit etre refuse.")

        with db(path) as connection:
            connection.execute(
                """INSERT INTO chat_turns
                   (request_id, payload_hash, conversation_id, status, owner_token)
                   VALUES ('turn-old', 'hash-old', 'conv-1', 'running', 'ancien-processus')"""
            )
        assert chat_turn_runtime.recover_orphaned_turns() == 1
        interrupted = []
        async for chunk in chat_turn_runtime.subscribe(
            request_id="turn-old", fingerprint="hash-old", conversation_id="conv-1",
            producer_factory=producer,
        ):
            interrupted.append(_event(chunk))
        assert interrupted[-1]["turnInterrupted"] is True
        assert starts == 1


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="marvin-chat-turn-") as directory:
        path = Path(directory) / "turns.db"
        with db(path) as connection:
            apply_migrations(connection, MIGRATIONS)
        asyncio.run(_exercise(path))
        with db(path) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert connection.execute(
                "SELECT status FROM chat_turns WHERE request_id = 'turn-1'"
            ).fetchone()[0] == "completed"
    print("Chat Turn Runtime OK - detach, replay, curseur et interruption sure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
