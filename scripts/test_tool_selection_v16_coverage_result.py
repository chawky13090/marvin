"""Validate the immutable aggregate retrospective coverage result."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.6/measurement-strategy-preregistration.json"
RESULT = ROOT / "benchmarks/tool-selection/v1.6/retrospective-coverage.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "complete_aggregate_retrospective_not_a_product_score"
    assert value["policy_sha256"] == sha(POLICY)
    assert value["source"] == {
        "user_message_count": 729,
        "database_opened_read_only": True,
        "tool_names_read": False,
        "tool_results_read": False,
    }
    expected = {
        "software.search": 1,
        "software.install": 13,
        "software.inventory": 0,
        "software.updates_check": 0,
        "software.upgrade": 0,
        "software.uninstall": 3,
        "software.manual_panel": 0,
    }
    assert value["coverage"]["counts_by_family"] == expected
    assert value["coverage"]["minimum"] == 5
    assert value["coverage"]["covered_by_real_usage_families"] == ["software.install"]
    assert value["coverage"]["eligible_r4_families"] == [family for family, count in expected.items() if count < 5]
    assert value["claims"] == {
        "independent_holdout": False,
        "product_quality_score": False,
        "r4_scope_only": True,
        "unrepresented_means_unassessed": True,
    }
    assert all(flag is False for flag in value["privacy"].values())
    serialized = RESULT.read_text(encoding="utf-8").casefold()
    for forbidden in ("@", "c:\\users", "message_id", "conversation_id", '"prompt"'):
        assert forbidden not in serialized
    print("Tool Selection v1.6 Coverage Result OK - install covered, six synthetic gaps, no product score")


if __name__ == "__main__":
    main()
