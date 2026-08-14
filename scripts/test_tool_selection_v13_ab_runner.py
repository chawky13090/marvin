"""Vérifie le runner A/B et son gel avant toute exécution benchmark."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    freeze = json.loads((BASE / "ab-runner-freeze.json").read_text(encoding="utf-8"))
    assert freeze["status"] == "frozen_after_preflight_before_benchmark_execution"
    assert freeze["preflight"]["control_activation_count"] == 0
    assert freeze["preflight"]["control_candidate_equality_count"] == 12
    assert freeze["preflight"]["business_tool_execution_count"] == 0
    assert freeze["benchmark"]["client_num_ctx"] is None
    assert freeze["decision"]["global_tool_action_success_minimum"] == 0.9
    assert freeze["decision"]["per_family_tool_action_success_minimum"] == 0.85
    assert freeze["authorization"]["benchmark_model_calls"] is False
    for relative, expected in freeze["frozen_hashes"].items():
        assert _sha(ROOT / relative) == expected, relative
    source = (ROOT / "scripts/run_tool_selection_v13_ab.py").read_text(encoding="utf-8")
    assert "business_tool" not in source or '"business_tool_execution_count": 0' in source
    assert "execute_registered_tool" not in source
    assert "tool_runtime.execute" not in source
    assert "build_canonical_tool_view" in source
    assert "enabled=True" in source
    assert '"num_ctx" not in payload["options"]' in source
    print("Tool selection v1.3 A/B runner OK - preflight frozen, no business execution authorized.")


if __name__ == "__main__":
    main()
