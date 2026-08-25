"""Pin the r6 manifest failure and prevent reuse of its Cloud responses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/tool-selection/v1.8"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    value = json.loads((BASE / "holdout-generation-abort-r6.json").read_text(encoding="utf-8"))
    assert value["status"] == "aborted_manifest_contract_error_no_public_holdout"
    assert value["freeze_sha256"] == _sha(BASE / "holdout-generation-freeze-r6.json")
    assert value["runner_sha256"] == _sha(ROOT / "scripts/generate_tool_selection_v18_holdout_r6.py")
    assert value["mechanical_findings"]["missing_key"] == "novelty"
    assert value["mechanical_findings"]["cloud_responses_reusable"] is False
    assert value["mechanical_findings"]["product_inference_authorized"] is False
    assert value["execution"]["authorization_consumed"] is True
    assert value["execution"]["stage_b_authorized"] is False
    for name in ("holdout-corpus-r6.json", "holdout-oracle-r6.json", "holdout-generation-report-r6.json"):
        assert not (BASE / name).exists()
    print("Tool Selection v1.8 Holdout Abort r6 OK - missing policy key pinned, no inference")


if __name__ == "__main__":
    main()
