"""Régressions déterministes Marvin Forge, sans LLM ni accès réseau."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import forge


def scenario(expectations: dict) -> dict:
    return {"id": "test-scenario", "name": "Test", "prompt": "Test", "expectations": expectations}


def main() -> int:
    clean = [
        {"type": "model_info", "model": "qwen-local"},
        {"type": "text", "content": "OK"},
        {"type": "done"},
    ]
    grade = forge.grade_trace(
        scenario({"require_done": True, "forbid_all_tools": True, "contains_all": ["OK"]}),
        clean,
        duration_ms=1200,
    )
    assert grade["success"] is True
    assert grade["score"] == 1.0

    unwanted_tool = [
        {"type": "tool_start", "toolName": "web_search"},
        {"type": "text", "content": "OK"},
        {"type": "done"},
    ]
    grade = forge.grade_trace(
        scenario({"forbid_all_tools": True}),
        unwanted_tool,
    )
    assert grade["success"] is False
    assert grade["tool_names"] == ["web_search"]

    required = forge.grade_trace(
        scenario({"required_tools": ["ai_model_council"], "max_tool_calls": 1}),
        [{"type": "tool_start", "toolName": "ai_model_council"}, {"type": "done"}],
    )
    assert required["success"] is True

    missing_event = forge.grade_trace(
        scenario({"required_event_types": ["cortex_provenance"]}),
        [{"type": "done"}],
    )
    assert missing_event["success"] is False

    assert forge._window_metric([True, True, True], 3, require_all=True) is True
    assert forge._window_metric([True, False, True], 3, require_all=True) is False
    assert forge._window_metric([False, False, True], 3, require_all=False) is True
    assert forge._window_metric([True], 3, require_all=True) is None

    print("Forge OK - graders, outils interdits/requis et métriques pass^k.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
