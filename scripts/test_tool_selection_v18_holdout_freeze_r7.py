"""Pin r7, including the complete offline preflight and every inherited policy dependency."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.8/holdout-generation-freeze-r7.json"


def _sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_cloud_generation_r7"
    expected = {
        "scripts/generate_tool_selection_v15_holdout_r3.py": value["runner_sha256"],
        "scripts/generate_tool_selection_v17_holdout_r4.py": value["bounded_review_wrapper_sha256"],
        "scripts/generate_tool_selection_v18_holdout_r5.py": value["r5_wrapper_sha256"],
        "scripts/generate_tool_selection_v18_holdout_r6.py": value["r6_review_wrapper_sha256"],
        "scripts/generate_tool_selection_v18_holdout_r7.py": value["r7_wrapper_sha256"],
        "scripts/test_tool_selection_v18_holdout_full_preflight_r7.py": value["full_offline_preflight_sha256"],
        "scripts/software_terminal_oracle_v1.py": value["terminal_oracle_source_sha256"],
        "benchmarks/tool-selection/v1.8/software-terminal-oracle-preregistration.json": value["terminal_oracle_policy_sha256"],
    }
    for path, digest in expected.items():
        assert _sha(path) == digest, path
    assert value["novelty"] == {
        "token_jaccard_maximum": 0.5,
        "compare_against_v1_2_v1_3_v1_4_and_development": True,
    }
    assert value["offline_preflight"]["expected_selected"] == 35
    assert value["offline_preflight"]["full_selection_path"] is True
    assert value["runtime_autonomy"]["marvin_runtime_behavior_changed"] is False
    assert value["authorization"]["stage_b_model_calls"] is False
    print("Tool Selection v1.8 Holdout Freeze r7 OK - full offline rehearsal pinned before Cloud")


if __name__ == "__main__":
    main()
