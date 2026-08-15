"""Verify the immutable raw result of the v1.4 model-only validation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.4"
RESULT = BASE / "validation-result.json"
FREEZE = BASE / "validation-result-freeze.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert freeze["status"] == "raw_result_frozen_before_assessment"
    assert sha256(RESULT) == freeze["result_sha256"]
    assert result["status"] == "complete_raw"
    assert result["runner_freeze_sha256"] == freeze["runner_freeze_sha256"]
    observations = result["observations"]
    assert len(observations) == freeze["observation_count"] == 400
    keys = Counter((row["id"], row["mode"], row["repetition"]) for row in observations)
    assert len(keys) == 400 and set(keys.values()) == {1}
    assert {row["mode"] for row in observations} == {"eco", "balanced", "performance", "max"}
    assert {row["repetition"] for row in observations} == {1, 2, 3, 4, 5}
    assert {row["observed_model"] for row in observations} == {"mistral-large-3:675b"}
    assert all(row["attempts"] == 1 for row in observations)
    assert result["business_tool_execution_count"] == freeze["business_tool_execution_count"] == 0
    assert result["host_side_effect_count"] == freeze["host_side_effect_count"] == 0
    assert result["product_activation_count"] == freeze["product_activation_count"] == 0
    assert freeze["assessment_must_be_separate"] is True
    assert freeze["raw_result_must_never_be_modified"] is True
    print("Tool selection v1.4 result OK - 400 choices, four modes, zero business execution.")


if __name__ == "__main__":
    main()
