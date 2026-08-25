"""Pin r5 as a runner nonconformity and deny product inference."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.8"


def _sha(name: str) -> str:
    return hashlib.sha256((BASE / name).read_bytes()).hexdigest()


def main() -> None:
    value = json.loads((BASE / "holdout-generation-abort-r5.json").read_text(encoding="utf-8"))
    diagnostic = json.loads((BASE / "holdout-generation-diagnostics-r5.json").read_text(encoding="utf-8"))
    assert value["status"] == "aborted_runner_nonconformity_no_public_holdout"
    assert value["freeze_sha256"] == _sha("holdout-generation-freeze-r5.json")
    assert value["diagnostic_sha256"] == _sha("holdout-generation-diagnostics-r5.json")
    assert value["runner_sha256"] == hashlib.sha256(
        (ROOT / "scripts/generate_tool_selection_v18_holdout_r5.py").read_bytes()
    ).hexdigest()
    assert all(
        row["consensus_nonempty"] == 20
        for row in diagnostic["counts_by_intent"].values()
    )
    assert diagnostic["counts_by_intent"]["software.search"]["adjudicator_valid"] == 0
    assert value["mechanical_findings"]["product_inference_authorized"] is False
    assert value["execution"]["authorization_consumed"] is True
    assert value["execution"]["stage_b_authorized"] is False
    assert not (BASE / "holdout-corpus-r5.json").exists()
    assert not (BASE / "holdout-oracle-r5.json").exists()
    print("Tool Selection v1.8 Holdout Abort r5 OK - oracle valid, reviewer scope nonconformity pinned")


if __name__ == "__main__":
    main()
