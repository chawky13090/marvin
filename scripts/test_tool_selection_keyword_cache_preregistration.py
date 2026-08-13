"""Vérifie le gel préalable de l'optimisation des motifs de sélection."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ABORTED = ROOT / "benchmarks/tool-selection/v1.0/ablation-run-aborted-v1.json"
POLICY = ROOT / "benchmarks/tool-selection/v1.1/keyword-regex-cache-preregistration.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    aborted = json.loads(ABORTED.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert aborted["status"] == "ABORTED_WITHOUT_RESULT"
    assert aborted["observations"]["result_artifact_written"] is False
    assert aborted["observations"]["product_data_mutation"] is False
    assert aborted["termination"]["remaining_runner_processes"] == 0
    assert sha256(ABORTED) == policy["aborted_observation"]["sha256"]
    assert policy["status"] == "frozen_before_product_optimization"
    assert policy["authorized_change"] == {
        "scope": "compile_and_cache_keyword_boundary_patterns",
        "cache_maximum_entries": 4096,
        "keyword_addition_or_removal": False,
        "tool_catalog_change": False,
        "ranking_score_change": False,
        "semantic_or_learned_route_change": False,
        "security_guard_change": False,
        "persistent_data_change": False,
    }
    assert policy["semantic_equivalence"]["old_and_new_keyword_predicate_mismatch_maximum"] == 0
    assert policy["semantic_equivalence"]["private_plaintext_output_forbidden"] is True
    assert policy["performance_acceptance"]["warm_median_speedup_minimum"] == 5.0
    assert policy["ablation_replay"]["stage_a_product_decision_still_forbidden"] is True
    frozen = subprocess.check_output(
        [
            "git",
            "show",
            f"{policy['source_commit']}:backend/agent_tool_selection.py",
        ],
        cwd=ROOT,
    )
    assert hashlib.sha256(frozen).hexdigest() == policy["source_agent_tool_selection_sha256"]
    assert sha256(ROOT / "scripts/run_tool_selection_ablation.py") == policy["source_runner_sha256"]
    print(
        "Tool Selection Keyword Cache Preregistration OK - "
        "abandon préservé, changement borné et équivalence obligatoire."
    )


if __name__ == "__main__":
    main()
