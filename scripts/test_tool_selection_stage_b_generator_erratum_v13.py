"""Verrouille l'adjudication indépendante uniforme du holdout Stage B."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.3.json"

def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_candidate_generation_before_holdout_freeze"
    assert value["candidate_artifacts_are_not_frozen"]
    assert value["observation"]["business_tool_execution_count"] == 0
    assert value["observation"]["benchmark_model_call_count"] == 0
    assert value["observation"]["specific_item_rule_forbidden"]
    change = value["authorized_change"]
    assert change["add_independent_adjudicator"]
    assert change["adjudicator_may_only_accept_or_exclude"]
    assert change["adjudicator_must_review_every_candidate"]
    assert change["adjudicator_cannot_rewrite_family_prompt_or_oracle"]
    assert change["benchmark_model_remains_unseen"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B adjudicator erratum OK - uniform accept/exclude only.")

if __name__ == "__main__": main()
