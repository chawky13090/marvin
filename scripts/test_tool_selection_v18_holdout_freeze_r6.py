"""Pin the single-use r6 generator and its text-only review boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.8/holdout-generation-freeze-r6.json"


def _sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_cloud_generation_r6"
    expected = {
        "scripts/generate_tool_selection_v15_holdout_r3.py": value["runner_sha256"],
        "scripts/generate_tool_selection_v17_holdout_r4.py": value["bounded_review_wrapper_sha256"],
        "scripts/generate_tool_selection_v18_holdout_r5.py": value["r5_wrapper_sha256"],
        "scripts/generate_tool_selection_v18_holdout_r6.py": value["r6_wrapper_sha256"],
        "scripts/test_tool_selection_v18_holdout_generator_r6.py": value["r6_canary_sha256"],
        "scripts/software_terminal_oracle_v1.py": value["terminal_oracle_source_sha256"],
        "benchmarks/tool-selection/v1.8/software-terminal-oracle-preregistration.json": value["terminal_oracle_policy_sha256"],
    }
    for path, digest in expected.items():
        assert _sha(path) == digest, path
    review = value["review_contract"]
    assert review["input_fields_exactly"] == ["id", "intent", "prompt"]
    assert all(review[field] is False for field in (
        "product_result_visible", "catalog_visible", "tool_name_visible",
        "terminal_call_visible", "safety_judgment_requested", "feasibility_judgment_requested",
    ))
    assert value["runtime_autonomy"] == {
        "marvin_runtime_imports_this_oracle": False,
        "marvin_runtime_behavior_changed": False,
        "public_tool_count_changed": False,
        "security_guards_changed": False,
    }
    assert value["authorization"]["stage_b_model_calls"] is False
    print("Tool Selection v1.8 Holdout Freeze r6 OK - text-only review, runtime autonomy unchanged")


if __name__ == "__main__":
    main()
