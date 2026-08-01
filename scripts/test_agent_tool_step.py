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

    computer = prepare_tool_call(
        "computer_control",
        {
            "action": "observe",
            "visual": "false",
            "capture_before": "TRUE",
            "embed": "invalide",
        },
    )
    assert computer.arguments["visual"] is False
    assert computer.arguments["capture_before"] is True
    assert computer.arguments["embed"] == "invalide"

    browser = prepare_tool_call(
        "web_browser_open",
        {"target": "https://example.com/", "max_chars": "30000"},
    )
    assert browser.arguments == {"url": "https://example.com/"}

    crawl = prepare_tool_call(
        "web_site_crawl",
        {"url": "https://example.com/", "max_pages": "5", "max_depth": "2"},
    )
    assert crawl.arguments["max_pages"] == 5
    assert crawl.arguments["max_depth"] == 2

    web_search = prepare_tool_call(
        "web_search",
        {"query": "actualité France", "limit": "20"},
    )
    assert web_search.arguments == {
        "query": "actualité France",
        "max_results": 20,
    }

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
    assert "projection de contexte" in projected["blob"]
    pdf_result = {
        "success": True,
        "text": "contenu intégral " * 350,
        "truncated": False,
        "chars": 5_950,
    }
    projected_pdf = json.loads(
        compact_tool_result(pdf_result, tool_name="pdf_read")
    )
    assert projected_pdf == pdf_result
    assert "projection de contexte" not in projected_pdf["text"]
    assert projected_pdf["truncated"] is False
    assert projected["items"][-1] == "…+10 éléments"

    file_page = {
        "success": True,
        "currentDir": r"C:\Users\Chawb\Documents",
        "count": 51,
        "total_count": 51,
        "offset": 0,
        "limit": 100,
        "has_more": False,
        "next_offset": None,
        "files": [
            {
                "name": f"document-{index}.txt",
                "type": "fichier",
                "size": "1 Ko",
                "path": f"C:/private/document-{index}.txt",
                "modified": "now",
            }
            for index in range(51)
        ],
    }
    projected_files = json.loads(compact_tool_result(
        file_page, max_chars=100, tool_name="file_list"
    ))
    assert len(projected_files["files"]) == 51
    assert projected_files["files"][-1]["name"] == "document-50.txt"
    assert projected_files["has_more"] is False
    assert "path" not in projected_files["files"][0]

    computer_result = {
        "success": True,
        "result": {
            "visual": {
                "image": "data:image/png;base64," + ("A" * 5_000),
                "frame_id": "fr_test",
                "width": 1280,
            },
            "ui": {"elements": [{"name": "Réserver", "element_ref": "el_test"}]},
        },
    }
    projected_computer = json.loads(
        compact_tool_result(
            computer_result,
            max_chars=1_000,
            tool_name="computer_control",
        )
    )
    assert "image" not in projected_computer["result"]["visual"]
    assert projected_computer["result"]["visual"]["frame_id"] == "fr_test"
    assert (
        projected_computer["result"]["ui"]["elements"][0]["element_ref"]
        == "el_test"
    )

    print(
        "Agent Tool Step OK - alias, JSON, contexte interne, PDF complet et projection bornée."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
