"""Pin the consumed r4 campaign and prohibit accidental promotion to Stage B."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.7"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    value = json.loads((BASE / "holdout-generation-abort-r4.json").read_text(encoding="utf-8"))
    diagnostic = json.loads((BASE / "holdout-generation-diagnostics-r4.json").read_text(encoding="utf-8"))
    assert value["status"] == "aborted_without_public_holdout"
    assert value["freeze_sha256"] == _sha(ROOT / value["freeze"])
    assert value["diagnostic_sha256"] == _sha(ROOT / value["diagnostic"])
    assert value["runner_sha256"] == _sha(ROOT / "scripts/generate_tool_selection_v17_holdout_r4.py")
    assert diagnostic["status"] == "aborted"
    assert diagnostic["failure_stage"] == "selection"
    assert diagnostic["failure_intent"] == "software.search"
    search = diagnostic["counts_by_intent"]["software.search"]
    assert search["oracle_a_nonempty"] == 20
    assert search["oracle_b_nonempty"] == 20
    assert search["consensus_nonempty"] == 0
    assert value["execution"]["authorization_consumed"] is True
    assert value["execution"]["stage_b_authorized"] is False
    assert value["execution"]["business_tool_execution_count"] == 0
    assert value["execution"]["host_side_effect_count"] == 0
    assert all(flag is False for flag in value["immutability"].values())
    assert not (BASE / "holdout-corpus-r4.json").exists()
    assert not (BASE / "holdout-oracle-r4.json").exists()
    print("Tool Selection v1.7 Holdout Abort r4 OK - disagreement preserved, Stage B denied")


if __name__ == "__main__":
    main()
