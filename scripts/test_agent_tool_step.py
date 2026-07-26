"""Régressions de préparation et projection d'une étape d'outil."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_tool_step import (
    compact_tool_result,
    inject_internal_context,
    prepare_tool_call,
)


def main() -> int:
    powershell = prepare_tool_call(
        "pc_run_powershell", '{"command":"Get-Date"}'
    )
    assert powershell.arguments == {"script": "Get-Date"}

    ssh = prepare_tool_call("ssh_connect", {"save": True, "host": "server"})
    assert ssh.name == "ssh_connection_save"
    assert ssh.arguments == {"host": "server"}

    malformed = prepare_tool_call("calculator", "[invalid")
    assert malformed.arguments == {}

    status = prepare_tool_call(
        "code_workspace_status", {"mission_id": "mission-1"}
    )
    assert json.loads(status.read_signature) == {
        "mission_id": "mission-1",
        "tool": "code_workspace_status",
    }

    internal = inject_internal_context(
        "code_workspace_start", {"request": "code"}, "conv-1"
    )
    assert internal["_conversation_id"] == "conv-1"
    assert "_conversation_id" not in {"request": "code"}
    explicit = inject_internal_context(
        "screenshot_list", {"conversation_id": "conv-other"}, "conv-1"
    )
    assert "_conversation_id" not in explicit

    small = {"success": True, "value": "ok"}
    assert json.loads(compact_tool_result(small)) == small
    large = {
        "success": True,
        "message": "message complet",
        "blob": "x" * 900,
        "items": list(range(30)),
    }
    projected = json.loads(compact_tool_result(large, max_chars=100))
    assert projected["success"] is True
    assert projected["message"] == "message complet"
    assert "chars tronqués" in projected["blob"]
    assert projected["items"][-1] == "…+10 éléments"

    print(
        "Agent Tool Step OK - alias, JSON, contexte interne, signature et projection bornée."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
