"""Validate the one-use r3 Cloud generation authorization and frozen runner."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "benchmarks/tool-selection/v1.5/holdout-generation-freeze-r3.json"
PREREG = ROOT / "benchmarks/tool-selection/v1.5/holdout-observability-preregistration-r3.json"
RUNNER = ROOT / "scripts/generate_tool_selection_v15_holdout_r3.py"
FREEZE_COMMIT = "3fe2c5f5f118efb3a4fd17e5753387676c05c3b6"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha(commit: str, path: str) -> str:
    value = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    value = json.loads(FREEZE.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_cloud_generation_r3"
    assert value["runner_sha256"] == sha(RUNNER)
    assert value["observability_preregistration_sha256"] == sha(PREREG)
    assert value["supersedes_freeze_sha256"] == prereg["historical_inputs"]["r2_freeze"]["sha256"]
    assert value["prior_abort_sha256"] == prereg["historical_inputs"]["r2_abort"]["sha256"]
    assert value["author_pool_per_intent"] == 20
    assert value["target_per_intent"] == 5
    assert value["thresholds_and_filters_unchanged"] is True
    assert value["intents"] == list({
        "software.search": 0,
        "software.install": 0,
        "software.inventory": 0,
        "software.updates_check": 0,
        "software.upgrade": 0,
        "software.uninstall": 0,
        "software.manual_panel": 0,
    })
    assert len({role["model"].split(":", 1)[0] for role in value["roles"].values()}) == 5
    assert all(len(role["digest"]) == 64 for role in value["roles"].values())
    # La campagne r3 est consommée et liée au commit de gel. Les sources produit
    # courantes doivent pouvoir évoluer sans réécrire ni invalider cette preuve.
    for path, expected in value["frozen_product_sources_sha256"].items():
        assert git_blob_sha(FREEZE_COMMIT, path) == expected, path
    assert all(value["independence"].values())
    assert value["authorization"] == {
        "cloud_generation_calls": True,
        "benchmark_model_calls": False,
        "business_tool_execution": False,
        "host_side_effects": False,
        "single_use": True,
        "third_attempt_only": True,
    }
    assert value["privacy"] == {
        "synthetic_only": True,
        "personal_data_forbidden": True,
        "raw_cloud_responses_persisted": False,
        "client_num_ctx_forbidden": True,
        "diagnostic_aggregate_only": True,
    }
    assert value["aggregate_diagnostic"]["fields_equal_observability_preregistration"] is True
    print("Tool Selection v1.5 Holdout Freeze r3 OK - one use, Cloud generation only, product locked")


if __name__ == "__main__":
    main()
