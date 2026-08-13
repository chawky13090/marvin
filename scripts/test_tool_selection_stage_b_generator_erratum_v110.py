"""Verrouille le pool familial fixe Stage B v1.10."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.10.json"
def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_aggregate_survivor_diagnostic_before_holdout_freeze"
    assert value["candidate_artifacts_are_not_frozen"]
    assert value["observation"]["only_aggregate_survivor_counts_observed"]
    assert value["observation"]["individual_prompts_and_decisions_not_used_for_selection"]
    change = value["authorized_change"]
    assert change["author_calls_batched_by_family"]
    assert change["authored_candidates_per_family"] == 32
    assert change["selected_holdout_per_family_remains"] == 5
    assert change["selection_order_remains_author_order_after_all_filters"]
    assert change["all_filters_models_prompts_parameters_and_decision_rules_unchanged"]
    assert change["no_manual_case_selection"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B fixed family pool OK - 32 authored, five filtered, no manual selection.")
if __name__ == "__main__": main()
