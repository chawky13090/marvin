"""Recalcule le verdict mécanique de la campagne A/B v1.3."""
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
    assessment = json.loads((BASE / "ab-assessment.json").read_text(encoding="utf-8"))
    freeze = json.loads((BASE / "ab-runner-freeze.json").read_text(encoding="utf-8"))
    assert assessment["source_result_sha256"] == _sha(BASE / "ab-result.json")
    cells = result["aggregates"]
    current = [cells[mode]["current"] for mode in cells]
    facade = [cells[mode]["canonical_facade"] for mode in cells]
    assert max(item["accepted_rate"] for item in facade) == assessment["observed"]["facade_global_rate_range"]["maximum"]
    assert all(candidate["accepted_rate"] < baseline["accepted_rate"] for baseline, candidate in zip(current, facade, strict=True))
    assert max(item["families"]["software_management"]["rate"] for item in facade) == 0.3
    assert sum(item["candidate_membership_violations"] for item in facade) == 9
    threshold = freeze["decision"]["global_tool_action_success_minimum"]
    family_threshold = freeze["decision"]["per_family_tool_action_success_minimum"]
    assert all(item["accepted_rate"] < threshold for item in facade)
    assert all(
        max(item["families"][family]["rate"] for item in facade) < family_threshold
        for family in ("application_launch", "software_management")
    )
    assert assessment["mechanical_verdict"]["rollback_required"] is True
    assert assessment["mechanical_verdict"]["general_activation_authorized"] is False
    assert assessment["mechanical_verdict"]["restricted_activation_authorized"] is False
    print("Tool selection v1.3 assessment OK - facade rejected mechanically; current K+L+S retained.")


if __name__ == "__main__":
    main()
