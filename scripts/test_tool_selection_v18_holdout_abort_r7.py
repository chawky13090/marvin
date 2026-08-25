"""Pin r7 reviewer disagreement and stop automatic synthetic retries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.8"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    value = json.loads((BASE / "holdout-generation-abort-r7.json").read_text(encoding="utf-8"))
    diagnostic = json.loads((BASE / "holdout-generation-diagnostics-r7.json").read_text(encoding="utf-8"))
    assert value["status"] == "aborted_independent_review_disagreement_no_public_holdout"
    assert value["freeze_sha256"] == _sha(BASE / "holdout-generation-freeze-r7.json")
    assert value["runner_sha256"] == _sha(ROOT / "scripts/generate_tool_selection_v18_holdout_r7.py")
    assert value["diagnostic_sha256"] == _sha(BASE / "holdout-generation-diagnostics-r7.json")
    uninstall = diagnostic["counts_by_intent"]["software.uninstall"]
    assert uninstall["consensus_nonempty"] == 20
    assert uninstall["adjudicator_valid"] == 0
    assert uninstall["critic_valid"] == 20
    assert uninstall["survivors_final"] == 0
    assert value["mechanical_findings"]["reviewer_disagreement_cause_known"] is False
    assert value["mechanical_findings"]["product_inference_authorized"] is False
    stop = value["campaign_stop_rule"]
    assert stop["automatic_r8_cloud_retry_authorized"] is False
    assert stop["threshold_reduction_authorized"] is False
    assert stop["single_reviewer_acceptance_authorized"] is False
    assert value["runtime_autonomy"]["public_tool_count"] == 364
    for name in ("holdout-corpus-r7.json", "holdout-oracle-r7.json", "holdout-generation-report-r7.json"):
        assert not (BASE / name).exists()
    print("Tool Selection v1.8 Holdout Abort r7 OK - disagreement pinned, automatic Cloud retries stopped")


if __name__ == "__main__":
    main()
