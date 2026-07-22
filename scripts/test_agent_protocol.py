"""Regressions des adaptateurs UI, Ollama et SSE."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from agent_protocol import encode_sse, to_ollama_messages


def main() -> int:
    converted = to_ollama_messages([
        {"role": "system", "content": "ignore"},
        {"role": "user", "content": [
            {"type": "text", "text": "analyse"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
            "fragment-invalide",
        ]},
        {"role": "assistant", "content": "", "toolInvocations": [{
            "toolName": "file_read", "args": {"path": "C:/a.txt"},
            "state": "result", "result": {"texte": "réussi"},
        }]},
        {"role": "assistant", "parts": [{"type": "text", "text": "suite"}]},
    ])
    assert converted[0] == {"role": "user", "content": "analyse", "images": ["QUJD"]}
    assert converted[1]["tool_calls"][0]["function"]["name"] == "file_read"
    assert json.loads(converted[2]["content"]) == {"texte": "réussi"}
    assert converted[3] == {"role": "assistant", "content": "suite"}

    stored = to_ollama_messages([{
        "role": "assistant", "content": "appel",
        "tool_calls": [{"toolName": "net_ping", "args": {"host": "127.0.0.1"}}],
    }])
    assert stored[0]["tool_calls"][0]["function"]["arguments"]["host"] == "127.0.0.1"

    event = encode_sse({"type": "text", "content": "été\nligne"})
    assert event.startswith("data: ") and event.endswith("\n\n")
    assert len(event[:-2].splitlines()) == 1
    assert json.loads(event[6:].strip())["content"] == "été\nligne"

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_to_ollama_messages" not in definitions
    assert "_sse" not in definitions
    print("Agent Protocol OK - texte, images, outils, résultats et SSE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
