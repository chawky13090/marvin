"""Verrouille l'exclusion conservative des décisions de revue manquantes."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "benchmarks/tool-selection/v1.2/holdout-generator-erratum-v1.8.json"
def main() -> None:
    value = json.loads(ERRATUM.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_incomplete_critic_batch_before_holdout_freeze"
    assert value["candidate_artifacts_are_not_frozen"]
    assert value["observation"]["semantic_result_was_not_used"]
    change = value["authorized_change"]
    assert change["missing_decision_maps_to_false"]
    assert change["duplicate_decision_maps_to_false"]
    assert change["invalid_type_maps_to_false"]
    assert change["true_requires_exactly_one_explicit_true"]
    assert change["false_never_becomes_true_by_default"]
    assert change["five_explicit_survivors_per_family_still_required"]
    source = ROOT / value["source_generator"]["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == value["source_generator"]["sha256"]
    print("Stage B review omission erratum OK - missing and duplicate map to false.")
if __name__ == "__main__": main()
