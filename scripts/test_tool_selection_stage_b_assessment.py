"""Recalcule les décisions mécaniques de l'assessment Stage B."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.2"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    result = json.loads((BASE / "stage-b-b1-result.json").read_text(encoding="utf-8"))
    assessment = json.loads((BASE / "stage-b-assessment.json").read_text(encoding="utf-8"))
    policy = json.loads((BASE / "stage-b-preregistration.json").read_text(encoding="utf-8"))
    erratum = BASE / "stage-b-b1-result-erratum-v1.1.json"
    assert assessment["source_result_sha256"] == sha(BASE / "stage-b-b1-result.json")
    assert assessment["source_erratum_sha256"] == sha(erratum)
    observations = result["observations"]
    violations = [row for row in observations if row["name"] and not row["candidate_membership_valid"]]
    assert len(violations) == assessment["observed"]["candidate_membership_violations"] == 30
    cells = [value for rows in result["aggregates"].values() for value in rows.values()]
    best = max(cells, key=lambda value: value["accepted_rate"])
    assert best["accepted_rate"] == assessment["observed"]["best_global_cell"]["accepted_tool_action_rate"]
    threshold = policy["decision"]["generalize_configuration_if"]["global_end_to_end_success_minimum"]
    assert threshold == assessment["pre_registered_thresholds"]["global_success_minimum"] == 0.9
    assert all(value["accepted_rate"] < threshold for value in cells)
    assert assessment["mechanical_verdict"]["B1_survivor_count"] == 0
    assert assessment["mechanical_verdict"]["B2_execution_state"] == "NOT_RUN_NO_B1_SURVIVOR"
    assert assessment["mechanical_verdict"]["simplification_authorized"] is False
    assert assessment["next_phase"]["reuse_of_this_holdout_for_optimization_forbidden"] is True
    print("Stage B assessment OK - no B1 survivor, K+L+S retained temporarily, B2 not run.")

if __name__ == "__main__":
    main()
