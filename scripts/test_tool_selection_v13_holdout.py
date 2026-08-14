"""Recalcule le gel, la confidentialité et les contrats du holdout v1.3."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    freeze = json.loads((BASE / "holdout-freeze-manifest.json").read_text(encoding="utf-8"))
    corpus = json.loads((BASE / "holdout-corpus.json").read_text(encoding="utf-8"))
    oracle = json.loads((BASE / "holdout-oracle.json").read_text(encoding="utf-8"))
    report = json.loads((BASE / "holdout-generation-report.json").read_text(encoding="utf-8"))
    for relative, expected in freeze["frozen_hashes"].items():
        assert _sha(ROOT / relative) == expected, relative
    items = corpus["items"]
    assert len(items) == freeze["counts"]["total"] == 20
    counts = Counter(item["family"] for item in items)
    assert counts == {"application_launch": 10, "software_management": 10}
    ids = [str(item["id"]) for item in items]
    assert len(ids) == len(set(ids))
    assert {str(item["id"]) for item in oracle["items"]} == set(ids)
    assert all(item["accepted_calls"] for item in oracle["items"])
    text = "\n".join(str(item["prompt"]) for item in items)
    assert re.search(r"[A-Z]:\\Users\\", text, re.IGNORECASE) is None
    assert re.search(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", text) is None
    assert report["counts"]["selected"] == 20
    assert report["business_tool_execution_count"] == 0
    assert report["host_side_effect_count"] == 0
    assert all(
        observation["client_num_ctx"] is None
        for rows in report["models"].values()
        for observation in rows
    )
    assert freeze["independence"]["corpus_is_burned_for_future_product_adjustment"] is True
    assert freeze["authorization"]["benchmark_model_calls"] is False
    print("Tool selection v1.3 holdout OK - 20 frozen synthetic intents, no execution, no personal data.")


if __name__ == "__main__":
    main()
