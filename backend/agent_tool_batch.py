"""Exécution, observation et persistance d'un lot d'appels d'outils."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable

from agent_observability import ObservationReceipt, ToolObservation
from agent_tool_dispatch import ToolDispatchRequest


async def execute_tool_batch(
    *,
    tool_calls: list[dict[str, Any]],
    assistant_content: str,
    ollama_messages: list[dict[str, Any]],
    conversation_id: str,
    request_id: str | None,
    user_query: str,
    active_model: str,
    permission_level: int,
    explicit_tool_names: set[str],
    required_tool_names: set[str],
    command_text_only: bool,
    read_signatures: set[str],
    runner_state: Any,
    dangerous_tools: set[str] | frozenset[str],
    prepare_tool_call: Callable[..., Any],
    inject_internal_context: Callable[..., dict[str, Any]],
    dispatch_tool: Callable[..., Awaitable[Any]],
    validate_tool_args: Callable[..., Any],
    execute_registered_tool: Callable[..., Awaitable[Any]],
    postprocess_tool_result: Callable[..., Awaitable[Any]],
    critique_action: Callable[..., Awaitable[Any]],
    scan_document: Callable[..., list[str]],
    record_tool_observation: Callable[[ToolObservation], Awaitable[ObservationReceipt | None]],
    record_long_chain: Callable[[str, int], None],
    is_tooling_failure: Callable[[Any], bool],
    compact_tool_result: Callable[[Any], str],
    create_message: Callable[..., Any],
    id_factory: Callable[[], str] | None = None,
    clock: Callable[[], float] = time.time,
) -> AsyncIterator[dict[str, Any]]:
    """Exécute séquentiellement un lot, en diffusant ses événements UI."""
    make_id = id_factory or (lambda: str(uuid.uuid4()))
    calls_for_db = [
        {
            "toolCallId": make_id(),
            "toolName": call["function"]["name"],
            "args": call["function"].get("arguments", {}),
        }
        for call in tool_calls
    ]
    create_message(
        conversation_id,
        "assistant",
        assistant_content,
        tool_calls=calls_for_db,
    )
    ollama_messages.append(
        {
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": tool_calls,
        }
    )

    results_for_db: list[dict[str, Any]] = []
    for tool_call, db_call in zip(tool_calls, calls_for_db):
        prepared = prepare_tool_call(
            tool_call["function"]["name"],
            tool_call["function"].get("arguments", {}),
        )
        tool_name = prepared.name
        arguments = prepared.arguments
        read_signature = prepared.read_signature
        tool_call["function"]["name"] = tool_name
        db_call["toolName"] = tool_name
        tool_call_id = db_call["toolCallId"]

        yield {
            "type": "tool_start",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "args": arguments,
        }

        started_at = clock()
        arguments = inject_internal_context(
            tool_name,
            arguments,
            conversation_id,
        )
        dispatch = await dispatch_tool(
            ToolDispatchRequest(
                name=tool_name,
                arguments=arguments,
                conversation_id=conversation_id,
                request_id=request_id,
                permission_level=permission_level,
                read_signature=read_signature,
                seen_read_signatures=read_signatures,
                explicit_names=explicit_tool_names,
                required_names=required_tool_names,
                command_text_only=command_text_only,
            ),
            validate=validate_tool_args,
            execute=execute_registered_tool,
        )
        result = dispatch.result
        arguments = dispatch.arguments
        duration_ms = max(0, int((clock() - started_at) * 1000))
        if read_signature:
            read_signatures.add(read_signature)

        result = await postprocess_tool_result(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            duration_ms=duration_ms,
            user_query=user_query,
            active_model=active_model,
            dangerous_tools=dangerous_tools,
            critique_action=critique_action,
            scan_document=scan_document,
        )
        if tool_name in {"ai_test_forge", "ai_code_forge"}:
            runner_state.update_blocking_outcome(tool_name, result)

        evidence = {
            "status": "unavailable",
            "proof_recorded": False,
            "sequence": None,
            "record_hash": None,
            "warnings": ["observation:missing_receipt"],
            "action_must_not_be_retried": True,
        }
        try:
            receipt = await record_tool_observation(
                ToolObservation(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    user_query=user_query,
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    duration_ms=duration_ms,
                )
            )
            if isinstance(receipt, ObservationReceipt):
                evidence = receipt.public_dict()
        except Exception as exc:
            evidence["warnings"] = [f"observation:{type(exc).__name__}"]

        yield {
            "type": "tool_end",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "result": result,
            "evidence": evidence,
        }
        long_chain_started = runner_state.record_tool(
            tool_name,
            arguments,
            result,
            tooling_failure=is_tooling_failure(result),
        )
        if long_chain_started:
            try:
                record_long_chain(user_query, runner_state.tool_count)
            except Exception:
                pass

        results_for_db.append(
            {
                "toolCallId": tool_call_id,
                "toolName": tool_name,
                "result": result,
                "evidence": evidence,
            }
        )
        ollama_messages.append(
            {
                "role": "tool",
                "content": compact_tool_result(result),
            }
        )

    create_message(
        conversation_id,
        "tool",
        json.dumps(results_for_db),
        tool_results=results_for_db,
    )
