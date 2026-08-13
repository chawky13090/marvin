"""Verrouille le sur-échantillonnage sans assouplissement du holdout."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.9.json"
def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_insufficient_family_survivors_before_holdout_freeze"
    assert value["candidate_artifacts_are_not_frozen"]
    assert value["observation"]["individual_acceptance_results_not_published_or_used"]
    change = value["authorized_change"]
    assert change["authored_candidates_per_family"] == 12
    assert change["selected_holdout_per_family_remains"] == 5
    assert change["selection_order_remains_author_order_after_all_filters"]
    assert change["all_oracle_schema_adjudication_critic_novelty_privacy_and_decision_rules_unchanged"]
    assert change["no_manual_case_selection"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B oversampling erratum OK - 12 authored, five filtered, no manual selection.")
if __name__ == "__main__": main()
