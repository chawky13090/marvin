"""Verify the one-use authorization for v1.4 model-only validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.4"
AUTHORIZATION = BASE / "validation-authorization.json"
RUNNER = BASE / "validation-runner-freeze.json"


def main() -> None:
    value = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    assert value["status"] == "authorized_once_before_result"
    assert value["runner_freeze_sha256"] == hashlib.sha256(RUNNER.read_bytes()).hexdigest()
    assert value["benchmark_model_calls"] is True
    assert value["maximum_calls"] == 400
    assert value["business_tool_execution"] is False
    assert value["host_side_effects"] is False
    assert value["product_activation"] is False
    assert value["security_guard_change"] is False
    assert value["partial_result_publication"] is False
    assert value["single_use"] is True
    print("Tool selection v1.4 authorization OK - 400 model choices maximum, zero business execution.")


if __name__ == "__main__":
    main()
