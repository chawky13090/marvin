"""Vérifie le résultat brut A/B v1.3 sans renégocier les seuils."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    result = json.loads((BASE / "ab-result.json").read_text(encoding="utf-8"))
    assert result["status"] == "complete_raw"
    assert result["runner_freeze_sha256"] == _sha(BASE / "ab-runner-freeze.json")
    assert result["authorization_sha256"] == _sha(BASE / "ab-authorization.json")
    assert result["holdout_freeze_sha256"] == _sha(BASE / "holdout-freeze-manifest.json")
    assert len(result["observations"]) == 360
    assert result["business_tool_execution_count"] == 0
    assert result["host_side_effect_count"] == 0
    assert result["product_activation_count"] == 0
    assert result["preflight"]["control_activation_count"] == 0
    for mode in ("eco", "balanced", "performance"):
        assert result["aggregates"][mode]["current"]["total"] == 60
        assert result["aggregates"][mode]["canonical_facade"]["total"] == 60
        assert result["aggregates"][mode]["canonical_facade"]["accepted_rate"] < result["aggregates"][mode]["current"]["accepted_rate"]
    print("Tool selection v1.3 A/B result OK - 360 choices, facade worse in all modes, no execution.")


if __name__ == "__main__":
    main()
