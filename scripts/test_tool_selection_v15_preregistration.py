"""Validate the immutable v1.5 software intent boundary preregistration."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.5/software-intent-boundary-preregistration.json"


def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["status"] == "frozen_before_product_change"
    assert policy["invariants"]["public_tool_count"] == 364
    assert policy["invariants"]["candidate_budget_unchanged"] is True
    assert policy["invariants"]["security_guards_unchanged"] is True
    assert policy["invariants"]["semantic_and_lexical_layers_may_not_reintroduce_forbidden_cross_action_tools"] is True

    contracts = policy["contracts"]
    expected = {
        "software.search", "software.install", "software.inventory",
        "software.updates_check", "software.upgrade", "software.uninstall",
        "software.manual_panel", "software.ambiguous",
    }
    assert set(contracts) == expected
    mutations = {"winget_install", "winget_upgrade", "winget_uninstall"}
    for name in ("software.search", "software.inventory", "software.updates_check", "software.manual_panel", "software.ambiguous"):
        assert mutations <= set(contracts[name]["forbidden_mutations"]), name
        assert not (mutations & set(contracts[name]["permitted_read_only"])), name

    assert contracts["software.install"]["terminal"] == ["winget_install"]
    assert "winget_uninstall" in contracts["software.install"]["forbidden"]
    assert contracts["software.uninstall"]["terminal"] == ["winget_uninstall"]
    assert "winget_install" in contracts["software.uninstall"]["forbidden"]
    assert contracts["software.upgrade"]["terminal"] == ["winget_upgrade"]
    assert "winget_uninstall" in contracts["software.upgrade"]["forbidden"]
    assert not contracts["software.ambiguous"]["terminal"]

    canaries = policy["development_canaries"]
    assert set(canaries) == expected
    assert all(len(items) >= 2 for items in canaries.values())
    assert policy["contamination_controls"]["v1_4_holdout_prompts_forbidden_in_product_rules"] is True
    assert policy["contamination_controls"]["new_independent_holdout_required_for_product_claim"] is True
    print("Tool Selection v1.5 Preregistration OK - contracts=8 cross-action=closed")


if __name__ == "__main__":
    main()
