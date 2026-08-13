"""Vérifie l'autorisation v1.1 sans réécrire le pré-enregistrement v1.0."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.1/ablation-reauthorization.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["status"] == "frozen_after_behavior_equivalent_product_optimization"
    inherited = ROOT / policy["inherits"]["path"]
    proof = ROOT / policy["optimization_proof"]["path"]
    assert sha256(inherited) == policy["inherits"]["sha256"]
    assert sha256(proof) == policy["optimization_proof"]["sha256"]
    assert policy["inherits"]["all_datasets_modes_configurations_metrics_and_decision_rules_unchanged"] is True
    assert policy["optimization_proof"]["predicate_mismatch_count"] == 0
    assert policy["optimization_proof"]["keyword_hit_set_mismatch_count"] == 0
    runner = policy["runner_v1_1_authorization"]
    assert runner["embedding_batch_maximum"] == 32
    assert runner["single_and_batch_embedding_exact_equality_required"] is True
    assert runner["control_query_minimum"] >= 5
    assert runner["qdrant_thresholds_and_limits_unchanged"] is True
    assert runner["candidate_postprocessors_unchanged"] is True
    assert runner["private_join_order_unchanged"] is True
    assert policy["product_decision_authorized"] is False
    for relative_path, expected in policy["product_sources_sha256"].items():
        frozen = subprocess.check_output(
            ["git", "show", f"{policy['source_commit']}:{relative_path}"],
            cwd=ROOT,
        )
        assert hashlib.sha256(frozen).hexdigest() == expected
    print(
        "Tool Selection Ablation Reauthorization OK - "
        "protocole v1.0 préservé, batching borné et décision produit interdite."
    )


if __name__ == "__main__":
    main()
