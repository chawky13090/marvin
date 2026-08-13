"""Verrouille la validation schéma et la critique adversariale Stage B."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.5.json"
def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_second_candidate_generation_before_holdout_freeze"
    assert value["candidate_artifacts_are_not_frozen"]
    assert value["observation"]["specific_item_rule_forbidden"]
    change = value["authorized_change"]
    assert change["validate_every_consensus_tool_action_and_constraint_against_frozen_tool_schema"]
    assert change["invalid_consensus_call_is_removed_before_model_review"]
    assert change["add_adversarial_coverage_critic"]
    assert change["critic_may_only_accept_or_exclude"]
    assert change["critic_reviews_every_candidate_after_dual_consensus"]
    assert change["critic_cannot_rewrite_family_prompt_or_oracle"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B schema and critic erratum OK - uniform mechanical plus adversarial checks.")
if __name__ == "__main__": main()
