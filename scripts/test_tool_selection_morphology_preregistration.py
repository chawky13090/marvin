"""Gel antérieur du correctif morphologique de présélection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks/tool-selection/v1.4/morphology-preregistration.json"
EXPECTED_SHA256 = "bda0dd5d9f3f34d0e4daf1e72cad5a2d0455abc3fecb91e99de8b73f946bfbdd"

raw = POLICY.read_bytes()
assert not raw.startswith(b"\xef\xbb\xbf")
assert b"\r\n" not in raw
assert hashlib.sha256(raw).hexdigest() == EXPECTED_SHA256
policy = json.loads(raw.decode("utf-8"))

assert policy["status"] == "frozen_before_product_change"
assert policy["problem"]["user_facing_spelling_must_be_correct"] is True
assert policy["problem"]["candidate_budget_must_not_increase"] is True
assert policy["design"]["minimum_prefix_characters"] == 7
assert policy["design"]["bounded_typo_distance"] == 1
assert policy["design"]["bounded_typo_applies_only_to_explicit_prefix_rules"] is True
assert policy["acceptance"]["ordinary_keyword_behavior_is_byte_for_byte_equivalent"] is True
assert policy["acceptance"]["new_independent_holdout_required_for_product_routing_claim"] is True
assert all(policy["forbidden"].values())
print("Tool selection morphology preregistration OK - frozen before product change")
