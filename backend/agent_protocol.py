"""Adaptateurs purs entre messages UI, Ollama et flux SSE Marvin."""

from __future__ import annotations

import json

from agent_tool_step import compact_tool_result


def to_ollama_messages(messages: list[dict]) -> list[dict]:
    result: list[dict] = []
    for message in messages:
        role = message.get("role", "user")
        if role not in ("user", "assistant", "tool"):
            continue

        content = ""
        images: list[str] = []
        raw_content = message.get("content")
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            for part in raw_content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    content += str(part.get("text", ""))
                elif part.get("type") in ("image_url", "image"):
                    image_url = part.get("image_url", {})
                    url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                    url = url or str(part.get("url", ""))
                    if url.startswith("data:") and "," in url:
                        images.append(url.split(",", 1)[1])
        elif isinstance(message.get("parts"), list):
            content = "".join(
                str(part.get("text", ""))
                for part in message["parts"]
                if isinstance(part, dict) and part.get("type") == "text"
            )

        if role == "tool":
            result.append({"role": "tool", "content": content})
            continue

        if role == "assistant":
            invocations = message.get("toolInvocations") or []
            if invocations:
                # A confirmation left pending in a previous turn is not a valid
                # Ollama tool exchange: a tool_call without its tool response,
                # followed by newer messages, is rejected with HTTP 400 by
                # several Ollama Cloud models. Reconstruct only completed pairs.
                completed_invocations = [
                    item
                    for item in invocations
                    if isinstance(item, dict) and item.get("state") == "result"
                ]
                if completed_invocations:
                    result.append({
                        "role": "assistant",
                        "content": content,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": invocation.get("toolName", ""),
                                    "arguments": invocation.get("args", {}),
                                }
                            }
                            for invocation in completed_invocations
                        ],
                    })
                    for invocation in completed_invocations:
                        result.append({
                            "role": "tool",
                            "content": compact_tool_result(
                                invocation.get("result", {}),
                                tool_name=str(invocation.get("toolName", "")),
                            ),
                        })
                elif content:
                    result.append({"role": "assistant", "content": content})
                continue

            stored_calls = message.get("tool_calls") or []
            if stored_calls:
                result.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "function": {
                                "name": call.get("toolName", ""),
                                "arguments": call.get("args", {}),
                            }
                        }
                        for call in stored_calls
                        if isinstance(call, dict)
                    ],
                })
                continue

        payload = {"role": role, "content": content}
        if role == "user" and images:
            payload["images"] = images
        result.append(payload)
    return result


def encode_sse(data: dict) -> str:
    """Encode un événement JSON sur une seule ligne data SSE, Unicode préservé."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
