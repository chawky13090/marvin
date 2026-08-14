"""Vérifie le pré-enregistrement immuable de la façade canonique v1.3."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.3/canonical-facade-preregistration.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["status"] == "frozen_before_product_implementation"
    assert policy["design"]["registry_tool_count_must_not_decrease"] == 364
    assert policy["design"]["new_public_executor"] is False
    assert policy["design"]["security_gateway_change"] is False
    assert policy["established_input"]["v1_2_holdout_reuse_for_optimization_forbidden"] is True
    assert policy["post_change_validation"]["activation_before_independent_result_forbidden"] is True
    assert policy["post_change_validation"]["minimum_intents_per_evaluated_family"] >= 10
    assert set(policy["canonical_actions"]) == {
        "application.launch",
        "software.search",
        "software.install",
        "software.list_installed",
        "software.list_upgrades",
        "software.upgrade",
        "software.uninstall",
    }
    for relative, expected in policy["frozen_product_sources_sha256"].items():
        assert _sha256(ROOT / relative) == expected, relative
    print("Canonical facade preregistration OK - product unchanged and holdout v1.2 forbidden for optimization.")


if __name__ == "__main__":
    main()
