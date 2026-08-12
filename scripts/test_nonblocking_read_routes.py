from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.responses import JSONResponse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import runtime_config as runtime_api
from api import coding as coding_api
from api import conversations as conversations_api
from api import vm_lab as vm_lab_api


def main() -> int:
    async def exercise() -> None:
        fake_learning = SimpleNamespace(
            count_learned=lambda: {"facts": 1, "qa": 1},
            list_learned=lambda kind, limit: [{"kind": kind, "limit": limit}],
        )
        with patch.dict(sys.modules, {"learning": fake_learning}):
            snapshot = await runtime_api.learning_list()
        assert snapshot["counts"] == {"facts": 1, "qa": 1}
        assert snapshot["facts"][0]["limit"] == 200
        assert snapshot["qa"][0]["limit"] == 100

        with patch.object(asyncio, "to_thread", new=AsyncMock(return_value={"source": "thread"})) as to_thread:
            assert await vm_lab_api.vm_lab_status() == {"source": "thread"}
            to_thread.assert_awaited_once_with(vm_lab_api.vm_lab.status)
        with patch.object(asyncio, "to_thread", new=AsyncMock(return_value={"job": "thread"})) as to_thread:
            assert await vm_lab_api.vm_lab_install_status() == {"job": "thread"}
            to_thread.assert_awaited_once_with(vm_lab_api.vm_lab_jobs.status)
        with patch.object(asyncio, "to_thread", new=AsyncMock(return_value={"coding": "thread"})) as to_thread:
            assert await coding_api.coding_overview() == {"coding": "thread"}
            to_thread.assert_awaited_once_with(coding_api._coding_overview_payload)

        main_thread_id = threading.get_ident()
        worker_thread_ids: list[int] = []
        heartbeat_ticks = 0
        finished = False
        original_json_response = JSONResponse

        def get_conversation(_cid: str) -> dict:
            worker_thread_ids.append(threading.get_ident())
            time.sleep(0.08)
            return {"id": "conversation-large", "title": "Conversation de test"}

        def get_messages(_cid: str) -> list[dict]:
            worker_thread_ids.append(threading.get_ident())
            return [
                {
                    "id": "assistant-message",
                    "role": "assistant",
                    "content": "Résultat prêt.",
                    "tool_calls": [
                        {
                            "toolCallId": "call-1",
                            "toolName": "file_find",
                            "args": {"query": "rapport"},
                        }
                    ],
                },
                {
                    "id": "tool-message",
                    "role": "tool",
                    "content": json.dumps(
                        [
                            {
                                "toolCallId": "call-1",
                                "toolName": "file_find",
                                "result": {"_marvin_projection": {"truncated": True}},
                            }
                        ]
                    ),
                    "tool_calls": None,
                    "tool_results": [
                        {
                            "toolCallId": "call-1",
                            "toolName": "file_find",
                            "result": {"files": ["rapport.pdf"]},
                            "evidence": {"verified": True},
                        }
                    ],
                },
            ]

        def build_json_response(*args, **kwargs):
            worker_thread_ids.append(threading.get_ident())
            return original_json_response(*args, **kwargs)

        async def heartbeat() -> None:
            nonlocal heartbeat_ticks
            while not finished:
                heartbeat_ticks += 1
                await asyncio.sleep(0.005)

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            with (
                patch.object(conversations_api.db, "get_conversation", side_effect=get_conversation),
                patch.object(
                    conversations_api.db,
                    "get_messages_by_conversation",
                    side_effect=get_messages,
                ),
                patch.object(
                    conversations_api.chat_turn_runtime,
                    "incomplete_tool_calls",
                    return_value={},
                ),
                patch.object(
                    conversations_api,
                    "JSONResponse",
                    side_effect=build_json_response,
                ),
            ):
                response = await conversations_api.get_conversation("conversation-large")
        finally:
            finished = True
            await heartbeat_task

        payload = json.loads(response.body)
        invocation = payload["messages"][0]["toolInvocations"][0]
        assert invocation["state"] == "result"
        assert invocation["result"] == {"files": ["rapport.pdf"]}
        assert heartbeat_ticks >= 5, heartbeat_ticks
        assert worker_thread_ids
        assert all(thread_id != main_thread_id for thread_id in worker_thread_ids)

        legacy_messages = get_messages("legacy")
        legacy_messages[1].pop("tool_results")
        legacy_messages[1]["content"] = json.dumps(
            [
                {
                    "toolCallId": "call-1",
                    "toolName": "file_find",
                    "result": {"files": ["archive-legacy.pdf"]},
                    "evidence": {"legacy": True},
                }
            ]
        )
        with (
            patch.object(
                conversations_api.db,
                "get_conversation",
                return_value={"id": "legacy", "title": "Historique"},
            ),
            patch.object(
                conversations_api.db,
                "get_messages_by_conversation",
                return_value=legacy_messages,
            ),
            patch.object(
                conversations_api.chat_turn_runtime,
                "incomplete_tool_calls",
                return_value={},
            ),
        ):
            legacy_response = await conversations_api.get_conversation("legacy")
        legacy_payload = json.loads(legacy_response.body)
        assert legacy_payload["messages"][0]["toolInvocations"][0]["result"] == {
            "files": ["archive-legacy.pdf"]
        }

        with patch.object(conversations_api.db, "get_conversation", return_value=None):
            try:
                await conversations_api.get_conversation("missing")
            except HTTPException as error:
                assert error.status_code == 404
                assert error.detail == "Conversation introuvable"
            else:
                raise AssertionError("Une conversation absente doit produire HTTP 404.")

    asyncio.run(exercise())
    print(
        "Nonblocking Read Routes OK - conversation DB read, reconstruction and JSON encoding, "
        "learning, Code Workspace and Hyper-V inventory leave the FastAPI event loop."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
