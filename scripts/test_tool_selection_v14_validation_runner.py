"""Verify the frozen v1.4 validation runner before model execution."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.4"
FREEZE = BASE / "validation-runner-freeze.json"
FROZEN_COMMIT = "a894126228908aca12b1b71dca54fe924de5a00d"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_sha256(relative: str) -> str:
    content = subprocess.run(
        ["git", "show", f"{FROZEN_COMMIT}:{relative}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    value = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_after_preflight_before_benchmark_execution"
    assert value["modes"] == {"eco": 18, "balanced": 40, "performance": 80, "max": 250}
    assert value["repetitions_per_intent"] == 5
    assert value["preflight"]["holdout_count"] == 20
    assert value["preflight"]["candidate_rows"] == 80
    assert value["preflight"]["benchmark_model_call_count"] == 0
    assert value["decision"]["global_average_never_masks_family_failure"] is True
    assert value["decision"]["no_threshold_or_product_change_after_result"] is True
    assert value["decision"]["holdout_burned_for_future_product_tuning"] is True
    assert value["authorization"] == {
        "benchmark_model_calls": False,
        "maximum_calls": 400,
        "single_use_artifact_required": True,
    }
    assert value["safety"]["business_tool_execution"] is False
    assert value["safety"]["host_side_effects"] is False
    assert value["safety"]["security_guards_are_not_ablated"] is True
    assert value["safety"]["tool_registry_count"] == 364
    for relative, expected in value["frozen_hashes"].items():
        # Cette preuve historique porte sur le produit gelé, jamais sur HEAD après
        # les évolutions suivantes. Lire le blob Git évite de rendre tout progrès
        # produit incompatible avec une campagne pourtant immuable et terminée.
        assert frozen_sha256(relative) == expected, relative
    result = BASE / "validation-result.json"
    if result.exists():
        authorization = json.loads((BASE / "validation-authorization.json").read_text(encoding="utf-8"))
        assert "validation-result.json" in authorization["consumed_when"]
        assert authorization["single_use"] is True
    print("Tool selection v1.4 runner OK - 4 modes, 5 repetitions, 400 calls locked, zero execution.")


if __name__ == "__main__":
    main()
