"""Immutabilité et indépendance du holdout de routage v1.4."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.4"
manifest = json.loads((BASE / "holdout-freeze-manifest.json").read_text(encoding="utf-8"))

for relative, expected in manifest["files"].items():
    raw = (ROOT / relative).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
    assert hashlib.sha256(raw).hexdigest() == expected

corpus = json.loads((BASE / "holdout-corpus.json").read_text(encoding="utf-8"))
oracle = json.loads((BASE / "holdout-oracle.json").read_text(encoding="utf-8"))
report = json.loads((BASE / "holdout-generation-report.json").read_text(encoding="utf-8"))
items = corpus["items"]
oracle_items = oracle["items"]
ids = [row["id"] for row in items]

assert corpus["schema"] == "marvin.tool-selection-v14-holdout/1.0"
assert oracle["schema"] == "marvin.tool-selection-v14-oracle/1.0"
assert len(ids) == len(set(ids)) == manifest["selected_count"] == 20
assert Counter(row["family"] for row in items) == Counter(manifest["family_counts"])
assert {row["id"] for row in oracle_items} == set(ids)
assert all(row["accepted_calls"] for row in oracle_items)
assert all(re.fullmatch(r"v14-(?:application-launch|software-management)-\d{2}", identity) for identity in ids)
assert report["business_tool_execution_count"] == 0
assert report["host_side_effect_count"] == 0
assert report["privacy"]["synthetic_only"] is True
assert report["privacy"]["raw_model_responses_published"] is False
assert report["generator_wrapper_sha256"] == hashlib.sha256(
    (ROOT / "scripts/generate_tool_selection_v14_holdout.py").read_bytes()
).hexdigest()
assert manifest["holdout_must_not_be_used_for_product_tuning"] is True
assert manifest["business_tool_execution_authorized"] is False

serialized = json.dumps(corpus, ensure_ascii=False)
for forbidden in ("C:\\Users\\", "@koios", "Chawb", "Chaouki"):
    assert forbidden.casefold() not in serialized.casefold()

print("Tool selection v1.4 holdout freeze OK - 20 unseen intents, zero execution")
