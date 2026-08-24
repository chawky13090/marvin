"""Offline canaries for r5; no Cloud or business tool call is made."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_tool_selection_v18_holdout_r5 as runner


def main() -> None:
    rows = [
        {"id": "generic-install", "intent": "software.install", "prompt": "opaque A"},
        {"id": "generic-search", "intent": "software.search", "prompt": "opaque B"},
        {"id": "generic-unknown", "intent": "software.unknown", "prompt": "opaque C"},
    ]
    prompt = "CATALOGUE:\n[]\nDEMANDES:\n" + json.dumps(rows)
    response = runner._deterministic_oracle_response(prompt)
    by_id = {row["id"]: row["accepted_calls"] for row in response["items"]}
    assert by_id["generic-install"] == [
        {"tool": "winget_install", "action": None, "constraints": []}
    ]
    assert by_id["generic-search"] == [
        {"tool": "winget_search", "action": None, "constraints": []}
    ]
    assert by_id["generic-unknown"] == []

    changed_text = [dict(row, prompt="entirely different opaque text") for row in rows]
    changed_response = runner._deterministic_oracle_response(
        "CATALOGUE:\n[]\nDEMANDES:\n" + json.dumps(changed_text)
    )
    assert changed_response == response
    try:
        runner._requests_from_oracle_prompt("missing marker")
    except ValueError as exc:
        assert "sans demandes" in str(exc)
    else:
        raise AssertionError("Le prompt oracle sans lot doit échouer fermé.")
    print("Tool Selection v1.8 Holdout Generator r5 OK - terminal oracle calculable, prompt text ignored")


if __name__ == "__main__":
    main()
