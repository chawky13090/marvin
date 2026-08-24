"""Pin the single-use r5 generator before any Cloud call."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.8/holdout-generation-freeze-r5.json"


def _sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_cloud_generation_r5"
    expected = {
        "scripts/generate_tool_selection_v15_holdout_r3.py": value["runner_sha256"],
        "scripts/generate_tool_selection_v17_holdout_r4.py": value["bounded_review_wrapper_sha256"],
        "scripts/generate_tool_selection_v18_holdout_r5.py": value["r5_wrapper_sha256"],
        "scripts/software_terminal_oracle_v1.py": value["terminal_oracle_source_sha256"],
        "benchmarks/tool-selection/v1.8/software-terminal-oracle-preregistration.json": value["terminal_oracle_policy_sha256"],
    }
    for path, digest in expected.items():
        assert _sha(path) == digest, path
    assert value["target_per_intent"] == 5
    assert len(value["intents"]) == 7
    assert value["execution_modes"]["oracle_a"].endswith("no_cloud_call")
    assert value["execution_modes"]["oracle_b"].endswith("no_cloud_call")
    assert value["admission"]["both_reviews_valid_required"] is True
    assert value["independence"]["terminal_oracle_cannot_read_prompt_text"] is True
    assert value["authorization"] == {
        "cloud_generation_calls": True,
        "business_tool_execution": False,
        "host_side_effects": False,
        "single_use": True,
        "fifth_attempt_only": True,
        "product_source_change": False,
        "stage_b_model_calls": False,
    }
    assert value["virtualization"] == {
        "docker_required": False,
        "hyper_v_required": False,
        "vmware_required": False,
    }
    print("Tool Selection v1.8 Holdout Freeze r5 OK - calculable oracle, dual review, one Cloud campaign")


if __name__ == "__main__":
    main()
