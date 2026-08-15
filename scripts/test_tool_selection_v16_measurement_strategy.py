"""Validate the three-corpus routing measurement strategy before extraction."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.6/measurement-strategy-preregistration.json"


def main() -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert value["status"] == "frozen_before_retrospective_coverage_recalculation"
    roles = value["corpus_roles"]
    assert set(roles) == {"owner_acceptance", "chronological_real_usage", "synthetic_gap_coverage"}
    assert roles["owner_acceptance"]["independence_claim"] is False
    assert roles["owner_acceptance"]["must_never_be_merged_into_generalization_score"] is True
    assert roles["chronological_real_usage"]["unrepresented_family_status"] == "UNASSESSED"
    coverage = value["retrospective_coverage"]
    assert coverage["independence_claim"] is False
    assert coverage["product_quality_claim_authorized"] is False
    assert coverage["minimum_requests_for_real_usage_coverage"] == 5
    assert coverage["r4_eligibility_rule"] == "count_less_than_5"
    assert len(coverage["families"]) == 7
    rubric = value["classification_rubric"]
    assert rubric["text_only"] is True
    assert rubric["executed_tool_names_forbidden"] is True
    assert rubric["tool_results_forbidden"] is True
    assert len(rubric["excluded_request_kinds"]) == 7
    assert all(value["r4_constraints"].values())
    assert all(value["privacy"].values())
    print("Tool Selection v1.6 Measurement Strategy OK - three corpora separated, r4 scope locked by coverage")


if __name__ == "__main__":
    main()
