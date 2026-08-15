"""Validate the immutable observability contract before the v1.5 r3 runner exists."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.5/holdout-observability-preregistration-r3.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_observability_implementation"
    for item in value["historical_inputs"].values():
        assert sha(ROOT / item["path"]) == item["sha256"], item["path"]
    fields = value["authorized_change"]["aggregate_counts_per_intent"]
    assert fields == [
        "authored_valid", "oracle_a_nonempty", "oracle_b_nonempty",
        "consensus_nonempty", "adjudicator_valid", "critic_valid",
        "both_reviews_valid", "novelty_valid", "survivors_final",
    ]
    assert all(value["privacy"].values())
    assert all(value["forbidden_change"].values())
    assert value["third_attempt"]["authorized_by_this_artifact"] is False
    assert value["third_attempt"]["no_cloud_call_before_separate_freeze"] is True
    print("Tool Selection v1.5 Observability Preregistration OK - aggregate only, r3 execution locked")


if __name__ == "__main__":
    main()
