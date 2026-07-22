"""Regressions de l'état observable du Runner agentique."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from agent_runner import RunnerState


def main() -> int:
    state = RunnerState(started_at=100.0)
    assert state.begin_step(0, 60, now=200.0) is True
    assert state.steps_used == 1
    assert state.begin_step(1, 60, now=159.0) is True
    assert state.begin_step(2, 60, now=160.0) is False
    assert state.stop_reason == "max_wall_seconds"

    state = RunnerState(started_at=100.0)
    long_chain_signals = []
    for index in range(9):
        long_chain_signals.append(state.record_tool(
            f"tool_{index}", {"value": index, "confirmed": True}, {"success": True},
            tooling_failure=False,
        ))
    assert state.successful_tools == 9 and state.failed_tools == 0
    assert long_chain_signals.count(True) == 1
    assert "confirmed" not in state.successful_calls[0]["args"]

    state.record_tool(
        "broken", {"host": "x"}, {"error": "outil inconnu"}, tooling_failure=True
    )
    assert state.failed_tools == 1 and state.succeeded is False
    assert "outil inconnu" in state.trace[-1]

    state.update_blocking_outcome("ai_test_forge", {"success": True, "production_ready": False})
    assert "ai_test_forge" in state.blocking_outcomes
    state.update_blocking_outcome("ai_test_forge", {"success": True, "production_ready": True})
    assert "ai_test_forge" not in state.blocking_outcomes
    state.update_blocking_outcome("ai_code_forge", {"success": True})
    assert "ai_code_forge" not in state.blocking_outcomes

    unfinished = RunnerState(started_at=100.0, steps_used=4)
    assert unfinished.finish_reason() == "max_tool_steps"
    with patch("agent_runner.time.monotonic", return_value=112.3456):
        usage = unfinished.budget_usage()
    assert usage == {
        "tool_steps": 4,
        "elapsed_seconds": 12.346,
        "stop_reason": "max_tool_steps",
    }

    import agent
    assert agent._RunnerState is RunnerState
    print("Agent Runner OK - étapes, budget, outils, blocages, traces et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
