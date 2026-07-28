"""Régressions d'exécution et persistance d'un lot d'outils."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_observability import ObservationReceipt
from agent_tool_batch import execute_tool_batch


class Runner:
    def __init__(self) -> None:
        self.tool_count = 0
        self.blocking: list[tuple] = []

    def update_blocking_outcome(self, name, result) -> None:
        self.blocking.append((name, result))

    def record_tool(self, name, arguments, result, *, tooling_failure) -> bool:
        self.tool_count += 1
        assert name == "ai_test_forge"
        assert arguments["conversation_id"] == "conv"
        assert tooling_failure is False
        return self.tool_count == 1


async def main() -> int:
    messages: list[dict] = []
    persisted: list[tuple] = []
    observed: list[object] = []
    long_chains: list[tuple] = []
    read_signatures: set[str] = set()
    runner = Runner()
    clock_values = iter((10.0, 10.125))

    async def dispatch(request, *, validate, execute):
        assert request.name == "ai_test_forge"
        assert validate("ai_test_forge", request.arguments) is None
        return SimpleNamespace(
            result=await execute(request.name, request.arguments, None, None),
            arguments=request.arguments,
        )

    async def execute(_name, arguments, _conversation_id, _request_id):
        return {"success": True, "production_ready": True, "args": arguments}

    async def postprocess(**kwargs):
        result = dict(kwargs["result"])
        result["duration"] = kwargs["duration_ms"]
        return result

    async def observe(value):
        observed.append(value)
        return ObservationReceipt(
            audit_recorded=True,
            execution_recorded=True,
            evidence_recorded=True,
            routing_learned=True,
            evidence_sequence=23,
            evidence_hash="b" * 64,
        )

    events = [
        event
        async for event in execute_tool_batch(
            tool_calls=[
                {
                    "function": {
                        "name": "ai_test_forge",
                        "arguments": {"path": "project"},
                    }
                }
            ],
            assistant_content="Je teste.",
            ollama_messages=messages,
            conversation_id="conv",
            request_id="request",
            user_query="teste",
            active_model="cloud:model",
            permission_level=2,
            explicit_tool_names=set(),
            required_tool_names={"ai_test_forge"},
            command_text_only=False,
            read_signatures=read_signatures,
            runner_state=runner,
            dangerous_tools=set(),
            prepare_tool_call=lambda name, arguments: SimpleNamespace(
                name=name,
                arguments=dict(arguments),
                read_signature="forge:project",
            ),
            inject_internal_context=lambda _name, arguments, conversation_id: {
                **arguments,
                "conversation_id": conversation_id,
            },
            dispatch_tool=dispatch,
            validate_tool_args=lambda _name, _arguments: None,
            execute_registered_tool=execute,
            postprocess_tool_result=postprocess,
            critique_action=lambda *_args, **_kwargs: None,
            scan_document=lambda *_args, **_kwargs: [],
            record_tool_observation=observe,
            record_long_chain=lambda query, count: long_chains.append((query, count)),
            is_tooling_failure=lambda _result: False,
            compact_tool_result=lambda result: f"compact:{result['success']}",
            create_message=lambda *args, **kwargs: persisted.append((args, kwargs)),
            id_factory=lambda: "tool-call-1",
            clock=lambda: next(clock_values),
        )
    ]
    assert [event["type"] for event in events] == ["tool_start", "tool_end"]
    assert events[1]["result"]["duration"] == 125
    assert events[1]["evidence"]["proof_recorded"] is True
    assert events[1]["evidence"]["sequence"] == 23
    assert read_signatures == {"forge:project"}
    assert runner.blocking[0][0] == "ai_test_forge"
    assert long_chains == [("teste", 1)]
    assert len(observed) == 1
    assert observed[0].duration_ms == 125
    assert [message["role"] for message in messages] == ["assistant", "tool"]
    assert messages[1]["content"] == "compact:True"
    assert len(persisted) == 2
    assert persisted[0][1]["tool_calls"][0]["toolCallId"] == "tool-call-1"
    assert persisted[1][1]["tool_results"][0]["result"]["production_ready"] is True
    assert persisted[1][1]["tool_results"][0]["evidence"]["record_hash"] == "b" * 64
    print("Agent Tool Batch OK - dispatch, événements, preuves, état et persistance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
