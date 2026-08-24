"""Validate the single-use r4 generation freeze without making Cloud calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.7/holdout-generation-freeze-r4.json"


def _sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_cloud_generation_r4"
    assert _sha("scripts/generate_tool_selection_v15_holdout_r3.py") == value["runner_sha256"]
    assert _sha("scripts/generate_tool_selection_v17_holdout_r4.py") == value["wrapper_sha256"]
    assert _sha("benchmarks/tool-selection/v1.7/software-remediation-preregistration.json") == (
        value["software_remediation_preregistration_sha256"]
    )
    assert value["target_per_intent"] == 5
    assert len(value["intents"]) == 7
    change = value["only_authorized_generator_change"]
    assert change["adjudicator_review_batching"] == "one_request_per_intent"
    assert change["critic_review_batching"] == "one_request_per_intent"
    assert change["exact_item_id_coverage_per_batch_required"] is True
    assert change["partial_batch_fails_closed"] is True
    assert all(
        change[key] is True
        for key in (
            "author_prompt_unchanged",
            "oracle_prompts_unchanged",
            "review_prompt_semantics_unchanged",
            "novelty_semantics_unchanged",
            "selection_thresholds_unchanged",
        )
    )
    assert len({contract["model"].split(":", 1)[0] for contract in value["roles"].values()}) == 5
    assert value["authorization"] == {
        "cloud_generation_calls": True,
        "benchmark_model_calls": False,
        "business_tool_execution": False,
        "host_side_effects": False,
        "single_use": True,
        "fourth_attempt_only": True,
        "product_source_change": False,
    }
    assert value["virtualization"] == {
        "hyper_v_required": False,
        "docker_required": False,
        "vmware_required": False,
    }
    print("Tool Selection v1.7 Holdout Freeze r4 OK - Cloud authorized once, no host execution")


if __name__ == "__main__":
    main()
