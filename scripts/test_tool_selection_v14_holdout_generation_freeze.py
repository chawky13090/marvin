"""Contrat du générateur indépendant du holdout v1.4."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "benchmarks/tool-selection/v1.4/holdout-generation-freeze.json"
policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def digest(relative: str) -> str:
    raw = (ROOT / relative).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
    return hashlib.sha256(raw).hexdigest()


assert policy["status"] == "frozen_before_cloud_generation"
assert digest("scripts/generate_tool_selection_v13_holdout.py") == policy["generator_sha256"]
assert digest("scripts/generate_tool_selection_v14_holdout.py") == policy["generator_wrapper_sha256"]
assert digest("benchmarks/tool-selection/v1.4/morphology-preregistration.json") == policy["preregistration_sha256"]
for relative, expected in policy["frozen_product_sources_sha256"].items():
    assert digest(relative) == expected
assert len({row["model"].split(":", 1)[0] for row in policy["roles"].values()}) == 5
assert policy["benchmark_model_excluded_from_generation"]["model"] not in {
    row["model"] for row in policy["roles"].values()
}
assert policy["authorization"] == {
    "holdout_generation_cloud_calls": True,
    "benchmark_model_calls": False,
    "product_activation": False,
    "business_tool_execution": False,
    "single_use": True,
}
assert policy["privacy_security"]["host_side_effects"] is False
assert policy["novelty"]["comparison_is_local_and_not_shown_to_cloud_roles"] is True

print("Tool selection v1.4 holdout generator freeze OK - product unchanged")
