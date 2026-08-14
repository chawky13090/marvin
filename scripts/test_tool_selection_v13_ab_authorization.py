"""Vérifie l'autorisation à usage unique de la campagne A/B v1.3."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    auth = json.loads((BASE / "ab-authorization.json").read_text(encoding="utf-8"))
    assert auth["status"] == "authorized_once_before_result"
    assert auth["runner_freeze_sha256"] == _sha(BASE / "ab-runner-freeze.json")
    assert auth["benchmark_model_calls"] is True
    assert auth["maximum_calls"] == 360
    assert auth["business_tool_execution"] is False
    assert auth["host_side_effects"] is False
    assert auth["product_activation"] is False
    assert auth["single_use"] is True
    print("Tool selection v1.3 A/B authorization OK - 360 model calls maximum, zero business execution.")


if __name__ == "__main__":
    main()
