"""Verrouille la substitution du critique incompatible avec JSON strict."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.6.json"
def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_critic_transport_failure_before_holdout_freeze"
    assert value["candidate_artifacts_are_not_frozen"]
    observation = value["observation"]
    assert observation["business_tool_execution_count"] == 0
    assert observation["benchmark_model_call_count"] == 0
    assert observation["replacement_probe_json_contract_passed"]
    assert observation["semantic_critic_result_was_not_scored"]
    change = value["authorized_change"]
    assert change["critic_model"] == "minimax-m2.7:cloud"
    assert change["same_critic_prompt_seed_temperature_top_p_and_role"]
    assert change["critic_may_only_accept_or_exclude"]
    assert change["all_other_rules_unchanged"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B critic substitution OK - JSON-compatible model, semantics unchanged.")
if __name__ == "__main__": main()
