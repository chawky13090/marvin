"""Recompute the frozen v1.4 assessment from the immutable raw result."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.4"
RESULT = BASE / "validation-result.json"
ASSESSMENT = BASE / "validation-assessment.json"


def family_stability(rows: list[dict]) -> float:
    grouped: dict[str, list[tuple[str | None, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["id"]].append(
            (row["name"], json.dumps(row["arguments"], sort_keys=True, separators=(",", ":")))
        )
    return sum(len(set(values)) == 1 for values in grouped.values()) / len(grouped)


def main() -> None:
    raw = RESULT.read_bytes()
    result = json.loads(raw)
    assessment = json.loads(ASSESSMENT.read_text(encoding="utf-8"))
    assert assessment["source_result_sha256"] == hashlib.sha256(raw).hexdigest()
    thresholds = json.loads((BASE / "validation-runner-freeze.json").read_text(encoding="utf-8"))["decision"]
    eligible: list[str] = []
    restricted: list[tuple[str, str]] = []
    for mode, aggregate in result["aggregates"].items():
        family_pass = all(
            row["rate"] >= thresholds["accepted_tool_action_per_family_minimum"]
            for row in aggregate["families"].values()
        )
        passed = (
            aggregate["accepted_rate"] >= thresholds["accepted_tool_action_global_minimum"]
            and family_pass
            and aggregate["repeat_stability"] >= thresholds["repeat_stability_minimum"]
            and aggregate["argument_schema_validity"] >= thresholds["argument_schema_validity_minimum"]
            and aggregate["candidate_membership_violations"] <= thresholds["candidate_membership_violation_maximum"]
            and aggregate["text_only_count"] / aggregate["total"] <= thresholds["text_only_maximum_rate"]
        )
        if passed:
            eligible.append(mode)
        for family, family_result in aggregate["families"].items():
            rows = [
                row for row in result["observations"]
                if row["mode"] == mode and row["family"] == family
            ]
            violations = sum(
                row["name"] is not None and not row["candidate_membership_valid"] for row in rows
            )
            if (
                family_result["rate"] >= thresholds["accepted_tool_action_per_family_minimum"]
                and family_stability(rows) >= thresholds["repeat_stability_minimum"]
                and violations == 0
            ):
                restricted.append((mode, family))
    assert eligible == assessment["global_generalization"]["eligible_modes"] == []
    expected_restricted = [(row["mode"], row["family"]) for row in assessment["restricted_candidates"]]
    assert sorted(restricted) == sorted(expected_restricted)
    assert assessment["decision"]["broad_product_validation"] is False
    assert assessment["decision"]["current_bundled_change_activation_authorized"] is False
    assert assessment["decision"]["v1_4_holdout_may_be_used_for_future_tuning"] is False
    assert assessment["latency_interpretation"]["inference_latency_claim_authorized"] is False
    assert assessment["next_cycle"]["must_use_new_holdout"] is True
    print("Tool selection v1.4 assessment OK - no generalization; application launch restricted in 3 modes.")


if __name__ == "__main__":
    main()
